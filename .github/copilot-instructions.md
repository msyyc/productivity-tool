# Copilot Instructions

## Key Terminology

- **swagger repo** or **rest repo** or **spec repo**: Refers to the [Azure/azure-rest-api-specs](https://github.com/Azure/azure-rest-api-specs) GitHub repository.
- **typespec repo**: Refers to the [microsoft/typespec](https://github.com/microsoft/typespec) GitHub repository.
- **azure typespec repo**: Refers to the [Azure/typespec-azure](https://github.com/Azure/typespec-azure.git) GitHub repository.
- **sdk repo**: Refers to any of the Azure SDK GitHub repositories, such as [Azure/azure-sdk-for-python](https://github.com/Azure/azure-sdk-for-python.git).
- **local repo**: The local clone of either the swagger repo or sdk repo on the user's machine. Usually located at `C:/dev/` like `C:/dev/azure-rest-api-specs` or `C:/dev/azure-sdk-for-python`.
- **autorest repo**: Refers to the [Azure/autorest.python](https://github.com/Azure/autorest.python.git) GitHub repository.
- **spector case**: Refers to cases in folder "packages/http-specs/specs" of typespec repo.
- **azure spector case**: Refers to cases in folder "packages/azure-http-specs/specs" of azure typespec repo.
- **autorest repo sync pipeline**: [autorest python sync pipeline](https://dev.azure.com/azure-sdk/internal/_build?definitionId=7257)
- **python emitter release pipeline**：[http-client-python](https://dev.azure.com/azure-sdk/internal/_build?definitionId=7189&_a=summary) and [typespec-python](https://dev.azure.com/azure-sdk/internal/_build?definitionId=7075)
- **autorest testserver repo**: Refers to [autorest.testserver repo](https://github.com/Azure/autorest.testserver)

## General Guidelines

- **bump http-client-python**: run python script `http_client_python_bump.py` under local typespec repo to update the version of http-client-python in typespec repo, then create a PR to merge the change.
- **bump typespec-python**: run python script `typespec_python_release.py` under local autorest repo to update the version of typespec-python in autorest repo, then create a PR to merge the change.
- **bump sdk repo**: run python script `emitter_package_update.py <sdk-repo-path>` to update emitter-package.json in local sdk repo to use the latest version of python generator tool, then create a PR to merge the change.
- **create release issue**: run `python release_issue_create.py --sdk-name <package-name> --tag <readme-tag>` to create a release request issue under Azure/sdk-release-request.
- **clean repo**: run `git reset HEAD && git checkout . && git clean -fd && git checkout origin/main && git pull origin main` under the local repo to clean all the local changes and sync with remote main branch.