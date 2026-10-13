## API contract comparison

8 breaking, 0 review

| Severity | Operation | Code | Location | Detail |
| --- | --- | --- | --- | --- |
| breaking | GET /health | OPERATION_REMOVED | /paths/~1health/get | Documented operation was removed. |
| breaking | POST /items | PARAMETER_REQUIRED | /paths/~1items/post/parameters/header:x-request-id/required | Request parameter became required. |
| breaking | POST /items | ENUM_CHANGED | /paths/~1items/post/requestBody/content/application~1json/schema/properties/category/enum | Request enum changed incompatibly. |
| breaking | POST /items | BOUND_CHANGED | /paths/~1items/post/requestBody/content/application~1json/schema/properties/name/maxLength | Request bound changed incompatibly. |
| breaking | POST /items | REQUIRED_CHANGED | /paths/~1items/post/requestBody/content/application~1json/schema/required/category | Required request property guarantee changed: category. |
| breaking | POST /items | TYPE_CHANGED | /paths/~1items/post/responses/201/content/application~1json/schema/properties/id/type | Response type set changed incompatibly. |
| breaking | POST /items | ENUM_CHANGED | /paths/~1items/post/responses/201/content/application~1json/schema/properties/status/enum | Response enum changed incompatibly. |
| breaking | POST /items | REQUIRED_CHANGED | /paths/~1items/post/responses/201/content/application~1json/schema/required/id | Required response property guarantee changed: id. |
