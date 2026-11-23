from core.security import SecurityManager
import tools


def test_dispatch_schema_and_policy_are_consistent():
    dispatch = set(tools.DISPATCH)
    schemas = {schema["function"]["name"] for schema in tools.TOOL_SCHEMAS}
    policies = set(SecurityManager().policies)

    assert dispatch == schemas
    assert dispatch == policies
