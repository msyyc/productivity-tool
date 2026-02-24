# TypeSpec Templates Reference

## Unbranded (Plain HTTP) Template

```typespec
import "@typespec/http";

using Http;

@service(#{title: "MyService"})
namespace MyService;

// -- models --

// -- operations --
```

### Available imports for unbranded

| Import | Using | Purpose |
|--------|-------|---------|
| `@typespec/http` | `Http` | HTTP decorators (@route, @get, @post, etc.) |
| `@typespec/rest` | `Rest` | REST resource helpers |
| `@typespec/openapi` | `OpenAPI` | OpenAPI decorators |
| `@typespec/versioning` | `Versioning` | API versioning support |
| `@typespec/xml` | — | XML serialization |
| `@typespec/sse` | — | Server-sent events |
| `@typespec/streams` | — | Streaming support |

### Unbranded compilable example

```typespec
import "@typespec/http";

using Http;

@service(#{title: "PetStore"})
namespace PetStore;

@error
model ApiError {
  @statusCode _: 500;
  message: string;
}

enum PetType {
  dog,
  cat,
  bird,
}

model Pet {
  id: int64;
  name: string;
  type: PetType;
  age?: int32;
  tags?: string[];
}

model PetList {
  items: Pet[];
  nextLink?: string;
}

@route("/pets")
namespace Pets {
  @get op list(@query skip?: int32, @query top?: int32): PetList;
  @post op create(@body pet: Pet): Pet;

  @route("/{petId}")
  @get op read(@path petId: int64): Pet;

  @route("/{petId}")
  @put op update(@path petId: int64, @body pet: Pet): Pet;

  @route("/{petId}")
  @delete op delete(@path petId: int64): void;
}
```

---

## Azure Flavor Template

```typespec
import "@typespec/http";
import "@typespec/rest";
import "@typespec/versioning";
import "@azure-tools/typespec-azure-core";

using Http;
using Rest;
using Versioning;
using Azure.Core;
using Azure.Core.Traits;

@service(#{title: "MyAzureService"})
namespace MyCompany.MyService;

// -- models (must have @resource decorator for ResourceOperations) --

// -- operations --
```

### Additional Azure imports

| Import | Using | Purpose |
|--------|-------|---------|
| `@azure-tools/typespec-azure-core` | `Azure.Core`, `Azure.Core.Traits` | Azure resource operations, traits, standard patterns |
| `@azure-tools/typespec-azure-resource-manager` | `Azure.ResourceManager` | ARM resource definitions |
| `@azure-tools/typespec-client-generator-core` | — | Client customization decorators |
| `@azure-tools/typespec-autorest` | — | Autorest compatibility |

### Azure compilable example

```typespec
import "@typespec/http";
import "@typespec/rest";
import "@typespec/versioning";
import "@azure-tools/typespec-azure-core";

using Http;
using Rest;
using Versioning;
using Azure.Core;
using Azure.Core.Traits;

@service(#{title: "ContosoWidgetManager"})
namespace Contoso.WidgetManager;

@resource("widgets")
model Widget {
  @key("widgetName")
  @visibility(Lifecycle.Read)
  name: string;
  manufacturerId: string;
  description?: string;
}

alias ServiceTraits = SupportsRepeatableRequests &
  SupportsConditionalRequests &
  SupportsClientRequestId;

alias Operations = Azure.Core.ResourceOperations<ServiceTraits>;

op getWidget is Operations.ResourceRead<Widget>;
op createOrUpdateWidget is Operations.ResourceCreateOrReplace<Widget>;
op deleteWidget is Operations.ResourceDelete<Widget>;
op listWidgets is Operations.ResourceList<Widget>;
```

---

## Common Type Reference

### Primitive types
`boolean`, `string`, `bytes`, `int8`, `int16`, `int32`, `int64`, `float32`, `float64`, `decimal`, `decimal128`, `plainDate`, `plainTime`, `utcDateTime`, `duration`, `url`

### Built-in HTTP response models
`NoContentResponse`, `OkResponse`, `CreatedResponse`, `AcceptedResponse`

### Decorators quick reference
- `@route("/path")` — HTTP route path
- `@get`, `@post`, `@put`, `@patch`, `@delete`, `@head` — HTTP methods
- `@path`, `@query`, `@header`, `@body` — Parameter locations
- `@statusCode` — HTTP status code (use literal: `@statusCode _: 200;`)
- `@error` — Mark model as error response
- `@doc("...")` — Documentation string
- `@service(#{title: "..."})` — Service metadata (use `#{}` syntax!)
- `@visibility(Lifecycle.Read)` — Visibility control
- `@resource("collectionName")` — Azure resource decorator
- `@key("keyName")` — Resource key field

### Optional properties
Use `?` suffix: `description?: string;`

### Arrays and dictionaries
- Array: `string[]` or `Array<string>`
- Dictionary: `Record<string>`

### Union types
`string | int32` or named: `union MyUnion { option1: string; option2: int32; }`

### Enum
```typespec
enum Color { red, green, blue }
```
