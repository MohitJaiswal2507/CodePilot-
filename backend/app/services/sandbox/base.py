"""
Base Sandbox Provider Interface.

Defines the contract that any sandbox execution engine (local Docker, remote HTTP runner, etc.)
must satisfy.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple
from app.schemas.execution import ExecutionResult, SupportedLanguage


class BaseSandboxProvider(ABC):
    """Abstract interface for code execution sandbox providers."""

    @abstractmethod
    def execute(
        self,
        code: str,
        language: SupportedLanguage,
        stdin: Optional[str] = None,
        custom_timeout: Optional[int] = None,
        custom_compile_timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute source code inside an isolated environment.

        Args:
            code: Source code string to execute.
            language: Target programming language ("python", "java", "cpp").
            stdin: Optional standard input data.
            custom_timeout: Optional execution timeout override in seconds.
            custom_compile_timeout: Optional compilation timeout override in seconds.

        Returns:
            Structured ExecutionResult with status, stdout, stderr, timings, and metadata.
        """
        pass

    @abstractmethod
    def check_available(self) -> Tuple[bool, str]:
        """
        Check if the provider runtime is available and reachable.

        Returns:
            (is_available, status_message_or_version)
        """
        pass
