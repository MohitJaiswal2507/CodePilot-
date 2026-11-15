"""
Local Docker Sandbox Execution Provider.

Wraps the hardened, ephemeral Docker container runner for local development,
test suites, and self-hosted worker nodes.
"""

from typing import Optional, Tuple
from app.schemas.execution import ExecutionResult, SupportedLanguage
from app.services.sandbox.base import BaseSandboxProvider


class LocalDockerProvider(BaseSandboxProvider):
    """
    Executes untrusted user code inside isolated, hardened, ephemeral Docker containers
    using the host system's Docker daemon.
    """

    def check_available(self) -> Tuple[bool, str]:
        """Verify that the host Docker CLI and daemon are available."""
        from app.services.sandbox_service import check_docker_available
        return check_docker_available()

    def execute(
        self,
        code: str,
        language: SupportedLanguage,
        stdin: Optional[str] = None,
        custom_timeout: Optional[int] = None,
        custom_compile_timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute code in a local Docker container enforcing kernel-level isolation,
        in-memory tmpfs, dropped capabilities, non-root user, streaming bounds,
        and randomized boundary markers.
        """
        from app.services.sandbox_service import execute_docker_code
        return execute_docker_code(
            code=code,
            language=language,
            stdin=stdin,
            custom_timeout=custom_timeout,
            custom_compile_timeout=custom_compile_timeout,
        )
