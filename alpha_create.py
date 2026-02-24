"""Create alpha folder under packages/http-client-python in the given typespec repo.

Usage:
    python alpha_create.py C:/dev/typespec
"""

import argparse
import os
import sys

CLIENT_TSP = """\
import "@typespec/http";

using TypeSpec.Http;

@service(#{ title: "My Service" })
namespace MyService;

model Widget {
  id: string;
  name: string;
}

@route("/widgets")
interface Widgets {
  @get list(): Widget[];
  @get read(@path id: string): Widget;
  @post create(@body widget: Widget): Widget;
}
"""

TSPCONFIG_YAML = """\
emit:
 - "@typespec/http-client-python"
options:
 "@typespec/http-client-python":
   flavor: azure
"""


def main():
    parser = argparse.ArgumentParser(
        description="Create the alpha folder under packages/http-client-python in a TypeSpec repository. "
                    "The folder contains client.tsp and tspconfig.yaml with predefined content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python alpha_create.py <path_to_typespec_repo>
  python alpha_create.py C:/dev/typespec
""",
    )
    parser.add_argument("typespec_repo_path", type=str, help="Path to the root of the TypeSpec repository")
    args = parser.parse_args()

    typespec_path = args.typespec_repo_path
    alpha_dir = os.path.join(typespec_path, "packages", "http-client-python", "alpha")
    os.makedirs(alpha_dir, exist_ok=True)

    client_tsp_path = os.path.join(alpha_dir, "client.tsp")
    with open(client_tsp_path, "w", newline="\n") as f:
        f.write(CLIENT_TSP)
    print(f"Created {client_tsp_path}")

    tspconfig_path = os.path.join(alpha_dir, "tspconfig.yaml")
    with open(tspconfig_path, "w", newline="\n") as f:
        f.write(TSPCONFIG_YAML)
    print(f"Created {tspconfig_path}")

    print("Done!")


if __name__ == "__main__":
    main()
