"""UI-independent guide state and strict model response contract."""
import uuid
import copy
import hashlib
from .files import GuideError, ProjectFiles


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


STRING = {'type': 'string'}


SCHEMA = obj({
    'accepted_requirements': STRING, 'conversation_change': STRING,
    'summary': STRING, 'question': STRING, 'choices': {'type': 'array', 'items': STRING},
    'blocked': STRING,
    'steps': {'type': 'array', 'items': obj({
        'id': STRING, 'path': STRING, 'anchor': STRING, 'line': {'type': 'integer'},
        'operation': {'type': 'string', 'enum': ['insert', 'replace', 'delete', 'create']},
        'code': STRING, 'diff': STRING, 'explanation': STRING})},
    'verdict': {'type': 'string', 'enum': ['not_reviewed', 'looks_complete', 'needs_changes', 'cannot_verify']},
    'findings': STRING, 'test_commands': {'type': 'array', 'items': STRING},
})


def check_schema(value, schema):
    kind = schema['type']
    valid = {'object': lambda: type(value) is dict, 'array': lambda: type(value) is list,
             'string': lambda: type(value) is str, 'integer': lambda: type(value) is int}[kind]()
    if not valid:
        raise GuideError('Codex returned an invalid response type. Retry.')
    if kind == 'object':
        if set(value) != set(schema['properties']):
            raise GuideError('Codex returned an incomplete response. Retry.')
        for key, child in schema['properties'].items():
            check_schema(value[key], child)
    elif kind == 'array':
        if len(value) > 100:
            raise GuideError('Codex response has too many items. Retry.')
        for item in value:
            check_schema(item, schema['items'])
    elif kind == 'string' and len(value) > 100000:
        raise GuideError('Codex response is too large. Retry.')
    if 'enum' in schema and value not in schema['enum']:
        raise GuideError('Codex returned an unsupported response value. Retry.')


def parse_guidance(data):
    """Check display structure only. Codex content and locations are used as supplied."""
    check_schema(data, SCHEMA)
    return data


class GuideSession:
    mode = 'code'
    def __init__(self, root, problem, window):
        self.id = uuid.uuid4().hex
        self.accepted_requirements = ''
        self.conversation_revision = 0
        self.pending_conversation_revision = 0
        self.pending_action = 'analyze'
        self.files = ProjectFiles(root)
        self.problem_text = self.files.read(problem)
        self.problem, self.window = problem, window
        self.request = None
        self.result = None
        self.index = 0
        self.choices = []

    def begin(self, action='analyze'):
        self.pending_action = action
        self.request = uuid.uuid4().hex
        return self.request

    def cancel(self):
        self.request = None

    def accept(self, request, data):
        if request != self.request:
            return False
        current_id = self.step['id'] if self.step else None
        parse_guidance(data)
        unchanged = (self.pending_action == 'adapt' and self.result is not None
                     and not data['conversation_change'].strip() and not data['question'] and not data['blocked'])
        if not unchanged:
            self.result = copy.deepcopy(data)
            self.accepted_requirements = data['accepted_requirements']
            self.index = next((i for i, s in enumerate(data['steps']) if s['id'] == current_id), 0)
        self.conversation_revision = self.pending_conversation_revision
        return True

    @property
    def step(self):
        return self.result['steps'][self.index] if self.result and self.result['steps'] else None

    def move(self, direction):
        if self.result and self.result['steps']:
            self.index = max(0, min(self.index + direction, len(self.result['steps']) - 1))


PROMPT_SCHEMA = obj({
    'approach': STRING, 'explanation': STRING, 'prompt': STRING, 'findings': STRING,
    'question': STRING, 'choices': {'type': 'array', 'items': STRING}, 'blocked': STRING,
    'status': {'type': 'string', 'enum': ['ready', 'clarification', 'cannot_verify', 'complete']},
    'accepted_requirements': STRING, 'conversation_change': STRING,
})


class PromptSession(GuideSession):
    """One outstanding prompt; history navigation never changes review context."""
    mode = 'prompt'

    def __init__(self, root, problem, window):
        super().__init__(root, problem, window)
        self.id = uuid.uuid4().hex
        self.history = []
        self.codex_session_id = None
        self.codex_session_name = ''
        self.terminal_id = None
        self.terminal_name = ''
        self.evidence = None
        self.pending_evidence = None
        self.conversation_revision = 0
        self.pending_conversation_revision = 0
        self.accepted_requirements = ''
        self.last_terminal_output = None
        self.reviewed_turns = []

    @staticmethod
    def evidence_key(terminal):
        if terminal.get('source') == 'codex_session':
            return (terminal['id'], terminal['execution_id'])
        # Status/revision-only changes are not new evidence of work on a prompt.
        return (terminal['id'], terminal['execution_id'],
                hashlib.sha256(terminal['output'].strip().encode()).hexdigest())

    def pin_terminal(self, terminal):
        if self.terminal_id == terminal['id']:
            self.terminal_name = terminal['name']
            return
        self.terminal_id = terminal['id']
        self.terminal_name = terminal['name']
        self.evidence = self.evidence_key(terminal)
        self.pending_evidence = None
        self.last_terminal_output = None

    def prepare_check(self, terminal):
        self.pending_evidence = self.check_terminal(terminal)

    def check_terminal(self, terminal):
        """Validate without changing state, so a cancelled worker stays read-only."""
        if terminal.get('source') != 'codex_session' and terminal['id'] != self.terminal_id:
            raise GuideError('The selected terminal changed. Select your Codex terminal again.')
        # Truncation can refer to old turns in the same interactive execution.
        # Keep the flag in review context so the reviewer assesses whether the
        # retained evidence supports this prompt, rather than rejecting all tails.
        if not terminal['output'].strip():
            raise GuideError('No output yet. Submit the prompt and wait for Codex, then check again.')
        key = self.evidence_key(terminal)
        if key == self.evidence or key in self.reviewed_turns:
            raise GuideError('No new Codex response. Submit the current prompt and wait for Codex before checking.')
        return key

    def accept(self, request, data):
        if request != self.request:
            return False
        check_schema(data, PROMPT_SCHEMA)
        if data['status'] == 'ready' and (not data['prompt'].strip() or data['question'] or data['blocked']):
            raise GuideError('Codex did not return one usable prompt. Retry.')
        if data['status'] != 'ready' and data['prompt'].strip():
            raise GuideError('Codex returned a prompt for an unresolved review. Retry.')
        if data['status'] == 'clarification' and (not data['question'] or not 2 <= len(data['choices']) <= 4):
            raise GuideError('Codex did not return usable clarification choices. Retry.')
        if len(data['accepted_requirements']) > 12000 or len(data['prompt']) > 16000:
            raise GuideError('Codex returned oversized prompt context. Retry.')
        self.result = copy.deepcopy(data)
        self.accepted_requirements = data['accepted_requirements']
        self.conversation_revision = self.pending_conversation_revision
        if data['status'] == 'ready':
            self.history.append(copy.deepcopy(data))
            self.history = self.history[-100:]
            self.index = len(self.history) - 1
        if data['status'] in ('ready', 'complete') and self.pending_evidence:
            self.evidence = self.pending_evidence
            self.reviewed_turns.append(self.pending_evidence)
            self.reviewed_turns = self.reviewed_turns[-100:]
        self.pending_evidence = None
        return True

    @property
    def step(self):
        return None

    @property
    def current(self):
        return self.history[self.index] if self.history else None

    def move(self, direction):
        if self.history:
            self.index = max(0, min(self.index + direction, len(self.history) - 1))

