"""JSON API layer that exposes the porting-workspace functionality to the web UI.

Every CLI capability in :mod:`src.main` has a matching function here that
returns plain JSON-serializable data (dicts / lists / scalars) so the browser
front-end can render it.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ..bootstrap_graph import build_bootstrap_graph
from ..command_graph import build_command_graph
from ..commands import (
    PORTED_COMMANDS,
    execute_command,
    find_commands,
    get_command,
    get_commands,
)
from ..direct_modes import run_deep_link, run_direct_connect
from ..models import PortingModule
from ..parity_audit import run_parity_audit
from ..permissions import ToolPermissionContext
from ..port_manifest import build_port_manifest
from ..query_engine import QueryEngineConfig, QueryEnginePort
from ..remote_runtime import run_remote_mode, run_ssh_mode, run_teleport_mode
from ..runtime import PortRuntime
from ..session_store import load_session
from ..setup import run_setup
from ..system_init import build_system_init_message
from ..tool_pool import assemble_tool_pool
from ..tools import (
    PORTED_TOOLS,
    execute_tool,
    find_tools,
    get_tool,
    get_tools,
)


class ApiError(Exception):
    """Raised for client errors; carries an HTTP status code."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses, Paths, and containers to JSON types."""

    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value


def _module(module: PortingModule) -> dict[str, Any]:
    return {
        'name': module.name,
        'responsibility': module.responsibility,
        'source_hint': module.source_hint,
        'status': module.status,
    }


# --- read-only inventory endpoints -----------------------------------------


def overview() -> dict[str, Any]:
    manifest = build_port_manifest()
    audit = run_parity_audit()
    return {
        'total_python_files': manifest.total_python_files,
        'top_level_modules': len(manifest.top_level_modules),
        'command_count': len(PORTED_COMMANDS),
        'tool_count': len(PORTED_TOOLS),
        'src_root': str(manifest.src_root),
        'archive_present': audit.archive_present,
        'parity': {
            'root_file_coverage': list(audit.root_file_coverage),
            'directory_coverage': list(audit.directory_coverage),
            'total_file_ratio': list(audit.total_file_ratio),
            'command_entry_ratio': list(audit.command_entry_ratio),
            'tool_entry_ratio': list(audit.tool_entry_ratio),
        },
    }


def summary() -> dict[str, Any]:
    return {'markdown': QueryEnginePort.from_workspace().render_summary()}


def manifest() -> dict[str, Any]:
    data = build_port_manifest()
    return {
        'src_root': str(data.src_root),
        'total_python_files': data.total_python_files,
        'markdown': data.to_markdown(),
        'top_level_modules': [
            {
                'name': mod.name,
                'path': mod.path,
                'file_count': mod.file_count,
                'notes': mod.notes,
            }
            for mod in data.top_level_modules
        ],
    }


def subsystems(limit: int = 32) -> dict[str, Any]:
    data = build_port_manifest()
    rows = [
        {
            'name': mod.name,
            'path': mod.path,
            'file_count': mod.file_count,
            'notes': mod.notes,
        }
        for mod in data.top_level_modules[: max(0, limit)]
    ]
    return {'count': len(rows), 'subsystems': rows}


def commands(
    limit: int = 20,
    query: str | None = None,
    include_plugin_commands: bool = True,
    include_skill_commands: bool = True,
) -> dict[str, Any]:
    if query:
        modules = find_commands(query, limit)
    else:
        modules = list(
            get_commands(
                include_plugin_commands=include_plugin_commands,
                include_skill_commands=include_skill_commands,
            )
        )[: max(0, limit)]
    return {
        'total': len(PORTED_COMMANDS),
        'query': query,
        'returned': len(modules),
        'commands': [_module(mod) for mod in modules],
    }


def tools(
    limit: int = 20,
    query: str | None = None,
    simple_mode: bool = False,
    include_mcp: bool = True,
    deny_tools: list[str] | None = None,
    deny_prefixes: list[str] | None = None,
) -> dict[str, Any]:
    if query:
        modules = find_tools(query, limit)
    else:
        permission_context = ToolPermissionContext.from_iterables(
            deny_tools or [], deny_prefixes or []
        )
        modules = list(
            get_tools(
                simple_mode=simple_mode,
                include_mcp=include_mcp,
                permission_context=permission_context,
            )
        )[: max(0, limit)]
    return {
        'total': len(PORTED_TOOLS),
        'query': query,
        'returned': len(modules),
        'tools': [_module(mod) for mod in modules],
    }


def show_command(name: str) -> dict[str, Any]:
    module = get_command(name)
    if module is None:
        raise ApiError(f'Command not found: {name}', status=404)
    return _module(module)


def show_tool(name: str) -> dict[str, Any]:
    module = get_tool(name)
    if module is None:
        raise ApiError(f'Tool not found: {name}', status=404)
    return _module(module)


def parity_audit() -> dict[str, Any]:
    audit = run_parity_audit()
    payload = to_jsonable(audit)
    payload['markdown'] = audit.to_markdown()
    return payload


def setup_report() -> dict[str, Any]:
    report = run_setup()
    payload = to_jsonable(report)
    payload['markdown'] = report.as_markdown()
    return payload


def command_graph() -> dict[str, Any]:
    graph = build_command_graph()
    return {
        'builtins': [_module(m) for m in graph.builtins],
        'plugin_like': [_module(m) for m in graph.plugin_like],
        'skill_like': [_module(m) for m in graph.skill_like],
        'markdown': graph.as_markdown(),
    }


def tool_pool(simple_mode: bool = False, include_mcp: bool = True) -> dict[str, Any]:
    pool = assemble_tool_pool(simple_mode=simple_mode, include_mcp=include_mcp)
    return {
        'simple_mode': pool.simple_mode,
        'include_mcp': pool.include_mcp,
        'tool_count': len(pool.tools),
        'tools': [_module(m) for m in pool.tools],
        'markdown': pool.as_markdown(),
    }


def bootstrap_graph() -> dict[str, Any]:
    graph = build_bootstrap_graph()
    return {'stages': list(graph.stages), 'markdown': graph.as_markdown()}


def system_init() -> dict[str, Any]:
    return {'markdown': build_system_init_message(trusted=True)}


# --- interactive / stateful endpoints --------------------------------------


def route(prompt: str, limit: int = 5) -> dict[str, Any]:
    if not prompt.strip():
        raise ApiError('A non-empty prompt is required.')
    matches = PortRuntime().route_prompt(prompt, limit=limit)
    return {
        'prompt': prompt,
        'count': len(matches),
        'matches': [
            {
                'kind': match.kind,
                'name': match.name,
                'source_hint': match.source_hint,
                'score': match.score,
            }
            for match in matches
        ],
    }


def bootstrap(prompt: str, limit: int = 5) -> dict[str, Any]:
    if not prompt.strip():
        raise ApiError('A non-empty prompt is required.')
    session = PortRuntime().bootstrap_session(prompt, limit=limit)
    return {
        'prompt': session.prompt,
        'context': to_jsonable(session.context),
        'setup': to_jsonable(session.setup),
        'startup_steps': list(session.setup.startup_steps()),
        'system_init_message': session.system_init_message,
        'routed_matches': [
            {
                'kind': m.kind,
                'name': m.name,
                'source_hint': m.source_hint,
                'score': m.score,
            }
            for m in session.routed_matches
        ],
        'command_execution_messages': list(session.command_execution_messages),
        'tool_execution_messages': list(session.tool_execution_messages),
        'stream_events': to_jsonable(session.stream_events),
        'turn_result': {
            'prompt': session.turn_result.prompt,
            'output': session.turn_result.output,
            'matched_commands': list(session.turn_result.matched_commands),
            'matched_tools': list(session.turn_result.matched_tools),
            'stop_reason': session.turn_result.stop_reason,
            'usage': to_jsonable(session.turn_result.usage),
        },
        'history': [
            {'title': e.title, 'detail': e.detail} for e in session.history.events
        ],
        'persisted_session_path': session.persisted_session_path,
        'markdown': session.as_markdown(),
    }


def turn_loop(
    prompt: str,
    limit: int = 5,
    max_turns: int = 3,
    structured_output: bool = False,
) -> dict[str, Any]:
    if not prompt.strip():
        raise ApiError('A non-empty prompt is required.')
    results = PortRuntime().run_turn_loop(
        prompt,
        limit=limit,
        max_turns=max_turns,
        structured_output=structured_output,
    )
    return {
        'prompt': prompt,
        'max_turns': max_turns,
        'structured_output': structured_output,
        'turns': [
            {
                'index': idx,
                'output': result.output,
                'stop_reason': result.stop_reason,
                'matched_commands': list(result.matched_commands),
                'matched_tools': list(result.matched_tools),
                'usage': to_jsonable(result.usage),
            }
            for idx, result in enumerate(results, start=1)
        ],
    }


def exec_command(name: str, prompt: str = '') -> dict[str, Any]:
    result = execute_command(name, prompt)
    return {
        'name': result.name,
        'source_hint': result.source_hint,
        'prompt': result.prompt,
        'handled': result.handled,
        'message': result.message,
    }


def exec_tool(name: str, payload: str = '') -> dict[str, Any]:
    result = execute_tool(name, payload)
    return {
        'name': result.name,
        'source_hint': result.source_hint,
        'payload': result.payload,
        'handled': result.handled,
        'message': result.message,
    }


def flush_transcript(prompt: str) -> dict[str, Any]:
    if not prompt.strip():
        raise ApiError('A non-empty prompt is required.')
    engine = QueryEnginePort.from_workspace()
    engine.submit_message(prompt)
    path = engine.persist_session()
    return {
        'session_id': engine.session_id,
        'path': path,
        'flushed': engine.transcript_store.flushed,
        'transcript_size': len(engine.transcript_store.entries),
    }


def get_session(session_id: str) -> dict[str, Any]:
    try:
        session = load_session(session_id)
    except FileNotFoundError as exc:
        raise ApiError(f'Session not found: {session_id}', status=404) from exc
    return {
        'session_id': session.session_id,
        'message_count': len(session.messages),
        'messages': list(session.messages),
        'input_tokens': session.input_tokens,
        'output_tokens': session.output_tokens,
    }


_MODE_RUNNERS = {
    'remote': run_remote_mode,
    'ssh': run_ssh_mode,
    'teleport': run_teleport_mode,
    'direct-connect': run_direct_connect,
    'deep-link': run_deep_link,
}


def run_mode(mode: str, target: str) -> dict[str, Any]:
    runner = _MODE_RUNNERS.get(mode)
    if runner is None:
        raise ApiError(
            f'Unknown mode: {mode}. Valid: {", ".join(sorted(_MODE_RUNNERS))}',
            status=404,
        )
    if not target.strip():
        raise ApiError('A non-empty target is required.')
    report = runner(target)
    return to_jsonable(report)
