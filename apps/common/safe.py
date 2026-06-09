from apps.common.agent_client import AgentClientError, agent_get


def safe_get(path: str, default):
    """Return agent_get(path) or `default` if agent-service is unavailable.
    Views use this so a down agent-service renders an 'unavailable' state, never 500."""
    try:
        return agent_get(path)
    except AgentClientError:
        return None if default is None else default
