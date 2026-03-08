from agent_messaging.application.command_router import CommandRouter

__all__ = ["AgentMessagingApp", "CommandRouter", "build_app", "main"]


def __getattr__(name: str):
    if name not in {"AgentMessagingApp", "build_app", "main"}:
        raise AttributeError(name)
    from agent_messaging.application.app import AgentMessagingApp, build_app, main

    exports = {
        "AgentMessagingApp": AgentMessagingApp,
        "build_app": build_app,
        "main": main,
    }
    return exports[name]
