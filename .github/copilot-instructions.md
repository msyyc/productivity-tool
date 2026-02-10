# Copilot Instructions

## Key Terminology

- **swagger repo** or **rest repo** or **spec repo**: Refers to the [Azure/azure-rest-api-specs](https://github.com/Azure/azure-rest-api-specs) GitHub repository.
- **typespec repo**: Refers to the [microsoft/typespec](https://github.com/microsoft/typespec) GitHub repository.
- **azure typespec repo**: Refers to the [Azure/typespec-azure](https://github.com/Azure/typespec-azure.git) GitHub repository.
- **sdk repo**: Refers to any of the Azure SDK GitHub repositories, such as [Azure/azure-sdk-for-python](https://github.com/Azure/azure-sdk-for-python.git).
- **local repo**: The local clone of either the swagger repo or sdk repo on the user's machine. Usually located at `C:/dev/` like `C:/dev/azure-rest-api-specs` or `C:/dev/azure-sdk-for-python`.
- **spector case**: Refers to cases in folder "packages/http-specs/specs" of typespec repo.
- **azure spector case**: Refers to cases in folder "packages/azure-http-specs/specs" of azure typespec repo.

## General Guidelines

- **URL lookup**: When the user asks you to find a specific string, file, or path within a specific repository, search the repository and return a direct HTTP URL (e.g., a GitHub permalink) so the user can click it to view the result in a browser immediately.