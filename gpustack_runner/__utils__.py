from __future__ import annotations

_BLANK_TAG = "latest"


def split_image(image: str, fill_blank_tag: bool = False) -> tuple:
    """
    Split the Docker completed image string into its image_name([registry/][namespace/]repository) and image_tag.

    Args:
        image:
            The Docker completed image string to split.
        fill_blank_tag:
            If True, fill the blank tag with `latest`.

    Returns:
        A tuple of (image_name, image_tag).

    """
    parts = image.rsplit("@", maxsplit=1)
    if len(parts) == 2:
        return tuple(parts)
    parts = image.rsplit(":", maxsplit=1)
    if len(parts) == 2 and "/" not in parts[1]:
        if fill_blank_tag:
            parts[1] = parts[1] or _BLANK_TAG
        return tuple(parts)
    return image, _BLANK_TAG if fill_blank_tag else None


def merge_image(image_name: str, image_tag: str | None = None) -> str:
    """
    Merge the Docker image and image_tag into a single string.

    Args:
        image_name:
            The Docker image name, in form of [registry/][namespace/]repository.
        image_tag:
            The Docker image tag.

    Returns:
        The completed Docker image string.

    """
    if not image_tag:
        return image_name
    if image_tag.startswith("sha256:"):
        return f"{image_name}@{image_tag}"
    return f"{image_name}:{image_tag}"


def parse_image(
    image: str,
    fill_blank_tag: bool = False,
) -> tuple[str | None, str | None, str, str | None] | None:
    """
    Parse the Docker image string into its components:
    registry, namespace, repository, and tag.

    Args:
        image:
            The Docker image string to parse.
        fill_blank_tag:
            If True, fill the blank tag with `latest`.

    Returns:
        A tuple of (registry, namespace, repository, tag).
        Registry, namespace, and tag can be None if not present.
        If the image string is invalid, return None.

    """
    image_reg, image_ns, image_repo, image_tag = (
        None,
        None,
        None,
        None,
    )
    image_rest = image.strip()

    # Get tag.
    image_rest, image_tag = split_image(image_rest, fill_blank_tag=fill_blank_tag)
    if not image_rest:
        return None

    # Get repository.
    parts = image_rest.rsplit("/", maxsplit=1)
    if len(parts) == 2:
        image_rest, image_repo = parts
    else:
        image_rest, image_repo = None, image_rest

    # Get namespace.
    if image_rest:
        parts = image_rest.rsplit("/", maxsplit=1)
        if len(parts) == 2:
            image_reg, image_ns = parts
        else:
            image_reg, image_ns = None, image_rest

    return image_reg, image_ns, image_repo, image_tag


def replace_image_with(
    image: str,
    registry: str | None = None,
    namespace: str | None = None,
    repository: str | None = None,
) -> str:
    """
    Replace the registry, namespace, and repository of a Docker image string.

    The given image string is parsed into its components (registry, namespace, repository, tag),
    and the specified components are replaced with the provided values.

    The format of a Docker image string is:
    [registry/][namespace/]repository[:tag|@digest]

    Args:
        image:
            The original Docker image string.
        registry:
            The new registry to use. If None, keep the original registry.
        namespace:
            The new namespace to use. If None, keep the original namespace.
        repository:
            The new repository to use. If None, keep the original repository.

    Returns:
        The modified Docker image string.

    """
    if not image or (not registry and not namespace and not repository):
        return image

    registry = registry.strip() if registry else None
    namespace = namespace.strip() if namespace else None
    repository = repository.strip() if repository else None

    image_reg, image_ns, image_repo, image_tag = parse_image(image)

    registry = registry or image_reg
    namespace = namespace or image_ns
    repository = repository or image_repo

    image_name = ""
    if registry:
        image_name += f"{registry}/"
    if namespace:
        image_name += f"{namespace}/"
    elif registry:
        image_name += "library/"
    image_name += repository

    image = merge_image(image_name, image_tag)
    return image
