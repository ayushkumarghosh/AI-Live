"""UI-independent guide state and strict model response contract."""
import uuid
from .files import GuideError, ProjectFiles


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


STRING = {'type': 'string'}


SCHEMA = obj({
    'summary': STRING, 'question': STRING, 'choices': {'type': 'array', 'items': STRING},
    'blocked': STRING,
    'steps': {'type': 'array', 'items': obj({
        'id': STRING, 'path': STRING, 'anchor': STRING, 'line': {'type': 'integer'},
        'operation': {'type': 'string', 'enum': ['insert', 'replace', 'delete', 'create']},
        'code': STRING, 'explanation': STRING})},
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
    def __init__(self, root, problem, window):
        self.files = ProjectFiles(root)
        self.problem_text = self.files.read(problem)
        self.problem, self.window = problem, window
        self.request = None
        self.result = None
        self.index = 0
        self.choices = []

    def begin(self):
        self.request = uuid.uuid4().hex
        return self.request

    def cancel(self):
        self.request = None

    def accept(self, request, data):
        if request != self.request:
            return False
        current_id = self.step['id'] if self.step else None
        self.result = parse_guidance(data)
        self.index = next((i for i, s in enumerate(data['steps']) if s['id'] == current_id), 0)
        return True

    @property
    def step(self):
        return self.result['steps'][self.index] if self.result and self.result['steps'] else None

    def move(self, direction):
        if self.result and self.result['steps']:
            self.index = max(0, min(self.index + direction, len(self.result['steps']) - 1))

