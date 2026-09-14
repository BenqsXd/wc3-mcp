"""Batch edits on JSON documents: set / append / remove at paths like players[0].name."""
import copy
import re

from ..errors import ToolError

_TOKEN = re.compile(r"([A-Za-z0-9_]+)|\[(\d+)\]")
_HINT = 'ops look like {"op": "set", "path": "players[0].name", "value": "Red"}; also append and remove'


def _parse_path(path) -> list:
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    tokens, pos = [], 0
    while pos < len(path):
        if path[pos] == "." and tokens and pos + 1 < len(path):
            pos += 1
        m = _TOKEN.match(path, pos)
        if not m:
            raise ValueError(f"bad path syntax at {path[pos:]!r}")
        tokens.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
        pos = m.end()
    return tokens


def _child(node, token):
    if isinstance(token, int):
        if not isinstance(node, list) or token >= len(node):
            raise ValueError(f"index [{token}] does not exist")
    elif not isinstance(node, dict) or token not in node:
        raise ValueError(f"key {token!r} does not exist")
    return node[token]


def apply_ops(doc: dict, ops: list) -> dict:
    out = copy.deepcopy(doc)
    for i, op in enumerate(ops):
        try:
            if not isinstance(op, dict):
                raise ValueError("each op must be an object")
            tokens = _parse_path(op.get("path"))
            parent = out
            for token in tokens[:-1]:
                parent = _child(parent, token)
            last, kind = tokens[-1], op.get("op")
            if kind in ("set", "append") and "value" not in op:
                raise ValueError(f"{kind} needs a value")
            if kind == "set":
                if isinstance(last, int):
                    _child(parent, last)
                elif not isinstance(parent, dict):
                    raise ValueError(f"cannot set key {last!r} on a list")
                parent[last] = copy.deepcopy(op["value"])
            elif kind == "append":
                target = _child(parent, last)
                if not isinstance(target, list):
                    raise ValueError("append target is not a list")
                target.append(copy.deepcopy(op["value"]))
            elif kind == "remove":
                _child(parent, last)
                del parent[last]
            else:
                raise ValueError(f"unknown op {kind!r}")
        except ValueError as e:
            raise ToolError("bad_op", str(e), hint=_HINT, op_index=i) from e
    return out
