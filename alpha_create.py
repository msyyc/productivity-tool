"""Create alpha folder under packages/http-client-python in the given typespec repo.

Usage:
    python alpha_create.py C:/dev/typespec
"""

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
    if len(sys.argv) < 2:
        print("Usage: python alpha_create.py <typespec_repo_path>")
        sys.exit(1)

    typespec_path = sys.argv[1]
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
