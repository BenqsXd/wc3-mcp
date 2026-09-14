import pytest

from wc3mcp.errors import ToolError
from wc3mcp.ops.edits import apply_ops


def test_set_append_remove_on_a_copy():
    doc = {"a": {"b": [1, 2]}, "c": "x"}
    out = apply_ops(doc, [{"op": "set", "path": "a.b[1]", "value": 5},
                          {"op": "append", "path": "a.b", "value": 7},
                          {"op": "set", "path": "a.new", "value": {"k": 1}},
                          {"op": "remove", "path": "c"}])
    assert out == {"a": {"b": [1, 5, 7], "new": {"k": 1}}}
    assert doc == {"a": {"b": [1, 2]}, "c": "x"}


def test_errors_carry_op_index():
    with pytest.raises(ToolError) as e:
        apply_ops({"a": [1]}, [{"op": "set", "path": "a[0]", "value": 2}, {"op": "set", "path": "a[5]", "value": 1}])
    assert e.value.code == "bad_op" and e.value.details["op_index"] == 1


@pytest.mark.parametrize("op", [
    {"op": "set", "path": "", "value": 1},
    {"op": "explode", "path": "a"},
    {"op": "append", "path": "c", "value": 1},
    {"op": "set", "path": "a..b", "value": 1},
    {"op": "set", "path": "missing.key", "value": 1},
    {"op": "remove", "path": "a[3]"},
    {"op": "set", "path": "a[0]"},
    "not an object",
])
def test_rejects_bad_ops(op):
    with pytest.raises(ToolError) as e:
        apply_ops({"a": [1], "c": "x"}, [op])
    assert e.value.code == "bad_op"
