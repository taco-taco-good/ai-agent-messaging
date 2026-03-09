__all__ = ["AgentMessagingApp", "build_app", "main"]


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
