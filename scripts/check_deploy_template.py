"""Offline textual deployment contract; not a Docker Compose renderer."""
import unittest
from pathlib import Path


class DeploymentTemplateTest(unittest.TestCase):
    def test_private_required_network(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "deploy/compose.yaml").read_text()
        example = (root / "deploy/.env.example").read_text()
        required = '${MCP_NETWORK:?Set the existing private Docker network}'
        self.assertEqual(compose.count(required), 1)
        self.assertIn('    name: "' + required + '"', compose)
        self.assertIn("  mcp_internal:\n    external: true", compose)
        self.assertRegex(compose, r"(?m)^      - mcp_internal$")
        self.assertNotRegex(compose, r"(?m)^\s*(ports|network_mode):")
        self.assertRegex(example, r"(?m)^MCP_NETWORK=$")
        self.assertNotIn("hermes_internal", compose)


if __name__ == "__main__":
    unittest.main()
