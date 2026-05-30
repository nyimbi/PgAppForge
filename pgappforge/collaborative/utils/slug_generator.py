"""
Slug generation utilities for collaborative features.

Provides centralized, configurable slug generation with multiple uniqueness strategies.
"""

import re
import uuid
from enum import Enum
from typing import Callable, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SlugGenerationStrategy(Enum):
    """Slug generation uniqueness strategies."""

    COUNTER = "counter"  # Append incrementing counter: slug-1, slug-2, etc.
    UUID = "uuid"  # Append short UUID: slug-abc123de
    TIMESTAMP = "timestamp"  # Append timestamp: slug-1640995200


class SlugGenerator:
    """
    Centralized slug generation with configurable uniqueness strategies.

    Features:
    - Consistent slug formatting across all collaborative entities
    - Multiple uniqueness strategies (counter, UUID, timestamp)
    - Database uniqueness checking with custom query functions
    - Configurable maximum attempts to prevent infinite loops
    - Comprehensive logging and error handling

    Example usage:
        generator = SlugGenerator(strategy=SlugGenerationStrategy.COUNTER)
        slug = generator.generate(
            name="My Workspace",
            uniqueness_checker=lambda slug: not workspace_exists(slug)
        )
    """

    def __init__(
        self,
        strategy: SlugGenerationStrategy = SlugGenerationStrategy.COUNTER,
        max_attempts: int = 100,
    ):
        """
        Initialize slug generator.

        Args:
            strategy: Uniqueness strategy to use
            max_attempts: Maximum attempts to find unique slug
        """
        self.strategy = strategy
        self.max_attempts = max_attempts

    def generate(
        self,
        name: str,
        uniqueness_checker: Callable[[str], bool],
        max_length: Optional[int] = None,
    ) -> str:
        """
        Generate a unique slug for the given name.

        Args:
            name: Source name to convert to slug
            uniqueness_checker: Function that returns True if slug is unique
            max_length: Maximum length for the slug (truncates base if needed)

        Returns:
            Unique slug string

        Raises:
            ValueError: If unable to generate unique slug within max_attempts
        """
        try:
            # Generate base slug
            base_slug = self._create_base_slug(name)

            # Truncate if max_length specified
            if max_length:
                # Reserve space for uniqueness suffix
                max_base_length = max_length - 20  # Reserve space for suffix
                if len(base_slug) > max_base_length > 0:
                    base_slug = base_slug[:max_base_length].rstrip("-")

            # Check if base slug is already unique
            if uniqueness_checker(base_slug):
                logger.debug(f"Generated unique base slug: {base_slug}")
                return base_slug

            # Apply uniqueness strategy
            for attempt in range(1, self.max_attempts + 1):
                candidate_slug = self._apply_uniqueness_strategy(base_slug, attempt)

                # Truncate if necessary
                if max_length and len(candidate_slug) > max_length:
                    # Keep the suffix, truncate the base
                    suffix_start = candidate_slug.rfind("-")
                    if suffix_start > 0:
                        suffix = candidate_slug[suffix_start:]
                        truncated_base = base_slug[: max_length - len(suffix)].rstrip(
                            "-"
                        )
                        candidate_slug = f"{truncated_base}{suffix}"
                    else:
                        candidate_slug = candidate_slug[:max_length].rstrip("-")

                if uniqueness_checker(candidate_slug):
                    logger.debug(
                        f"Generated unique slug after {attempt} attempts: {candidate_slug}"
                    )
                    return candidate_slug

            # If we reach here, we couldn't generate a unique slug
            error_msg = f"Unable to generate unique slug for '{name}' after {self.max_attempts} attempts"
            logger.error(error_msg)
            raise ValueError(error_msg)

        except Exception as e:
            logger.error(f"Error generating slug for '{name}': {e}")
            raise

    def _create_base_slug(self, name: str) -> str:
        """
        Create base slug from name using consistent formatting rules.

        Args:
            name: Source name

        Returns:
            Base slug string
        """
        if not name or not isinstance(name, str):
            raise ValueError("Name must be a non-empty string")

        # Convert to lowercase and replace non-alphanumeric chars with hyphens
        slug = re.sub(r"[^a-zA-Z0-9-]", "-", name.lower())

        # Remove leading/trailing hyphens and collapse multiple hyphens
        slug = re.sub(r"-+", "-", slug).strip("-")

        # Ensure minimum length
        if not slug:
            slug = "item"  # Fallback for edge cases

        return slug

    def _apply_uniqueness_strategy(self, base_slug: str, attempt: int) -> str:
        """
        Apply uniqueness strategy to create candidate slug.

        Args:
            base_slug: Base slug to modify
            attempt: Current attempt number

        Returns:
            Candidate slug with uniqueness suffix
        """
        if self.strategy == SlugGenerationStrategy.COUNTER:
            return f"{base_slug}-{attempt}"

        elif self.strategy == SlugGenerationStrategy.UUID:
            # Use short UUID for compactness
            uuid_suffix = uuid.uuid4().hex[:8]
            return f"{base_slug}-{uuid_suffix}"

        elif self.strategy == SlugGenerationStrategy.TIMESTAMP:
            import time

            timestamp = int(time.time())
            return f"{base_slug}-{timestamp}"

        else:
            # Fallback to counter strategy
            logger.warning(f"Unknown strategy {self.strategy}, falling back to counter")
            return f"{base_slug}-{attempt}"


# Convenience functions for common use cases


def generate_workspace_slug(
    name: str,
    uniqueness_checker: Callable[[str], bool],
    strategy: SlugGenerationStrategy = SlugGenerationStrategy.COUNTER,
) -> str:
    """
    Generate unique workspace slug.

    Args:
        name: Workspace name
        uniqueness_checker: Function to check slug uniqueness
        strategy: Uniqueness strategy to use

    Returns:
        Unique workspace slug
    """
    generator = SlugGenerator(strategy=strategy)
    return generator.generate(name, uniqueness_checker, max_length=100)


def generate_team_slug(
    name: str,
    uniqueness_checker: Callable[[str], bool],
    strategy: SlugGenerationStrategy = SlugGenerationStrategy.UUID,
) -> str:
    """
    Generate unique team slug.

    Args:
        name: Team name
        uniqueness_checker: Function to check slug uniqueness
        strategy: Uniqueness strategy to use (default: UUID for teams)

    Returns:
        Unique team slug
    """
    generator = SlugGenerator(strategy=strategy)
    return generator.generate(name, uniqueness_checker, max_length=100)


def generate_resource_slug(
    name: str,
    uniqueness_checker: Callable[[str], bool],
    strategy: SlugGenerationStrategy = SlugGenerationStrategy.COUNTER,
) -> str:
    """
    Generate unique resource slug.

    Args:
        name: Resource name
        uniqueness_checker: Function to check slug uniqueness
        strategy: Uniqueness strategy to use

    Returns:
        Unique resource slug
    """
    generator = SlugGenerator(strategy=strategy)
    return generator.generate(name, uniqueness_checker, max_length=200)


# Database-aware helper function
def create_uniqueness_checker(
    session_factory: Callable,
    model_class: Any,
    slug_field: str = "slug",
    additional_filters: Optional[dict] = None,
) -> Callable[[str], bool]:
    """
    Create a uniqueness checker function for database models.

    Args:
        session_factory: Function that returns database session
        model_class: SQLAlchemy model class to check against
        slug_field: Name of the slug field in the model
        additional_filters: Additional filter conditions (e.g., {'team_id': 123})

    Returns:
        Function that returns True if slug is unique
    """

    def checker(slug: str) -> bool:
        try:
            session = session_factory()
            query = session.query(model_class).filter(
                getattr(model_class, slug_field) == slug
            )

            # Apply additional filters if provided
            if additional_filters:
                for field, value in additional_filters.items():
                    query = query.filter(getattr(model_class, field) == value)

            exists = query.first() is not None
            session.close()
            return not exists  # Return True if slug is unique (doesn't exist)

        except Exception as e:
            logger.error(f"Error checking slug uniqueness: {e}")
            session.close()
            return False  # Assume not unique on error (fail safe)

    return checker
