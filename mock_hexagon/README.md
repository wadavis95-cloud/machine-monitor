# Mock Hexagon

Run `make mock-hexagon` from the project root. Flask listens on `127.0.0.1:5003`. The default API key is `demo-key` and `MOCK_HEXAGON_API_KEY` overrides it. Send it in `X-API-Key` on every request.

```sh
curl -fsS -H 'X-API-Key: demo-key' \
  'http://127.0.0.1:5003/workorders?asset=ENG-003&status=open'
```

## Mock API

| Method and path | Response |
| --- | --- |
| `GET /assets` | Array of assets with `ID`, `NAME`, `LOCATION`, `CURRENT_CYCLE`, and `PARTS` |
| `GET /assets/<id>` | One asset or 404 |
| `GET /parts` | Array of parts with `ID`, `NAME`, `UOM`, `LEAD_DAYS`, `UNIT_COST`, and `STOCK`. Each stock row has `STORE`, `ON_HAND`, and `REORDER_POINT` |
| `GET /workorders` | Array of work orders filtered by optional `asset` and `status` query parameters. The `open` filter includes `OPEN` and `REQUESTED` |
| `GET /workorders/<id>` | One work order or request, or 404 |
| `POST /workrequests` | Work request with an assigned `ID` and status `REQUESTED` |
| `POST /partrequisitions` | Part requisition with an assigned `ID` and status `SUBMITTED` |
| `GET /references?reference=<value>` | Array of matching records with `ID`, `REFERENCE`, and `KIND` (`WORK_REQUEST` or `PART_REQUISITION`). An unknown reference returns an empty array |

Work orders use `ASSET: {"ID": "..."}`, `STATUS: {"CODE": "..."}`, and `ORDER_TYPE: {"CODE": "REPAIR"}` or `"PREVENTIVE"`. Optional failure codes appear under `PROBLEM`, `CAUSE`, and `REMEDY`, each as a code object or null. Work order and asset part lists use `PARTS: [{"PART": {"ID": "..."}, "QUANTITY": 1}]`.

A work request requires `REFERENCE`, an `ASSET` object for a known engine, and `SUMMARY`. `ORDER_TYPE` defaults to `REPAIR`. Example body for `POST /workrequests`.

```json
{
  "REFERENCE": "draft-123",
  "ASSET": {"ID": "ENG-001"},
  "SUMMARY": "Inspect probe connector",
  "COMMENTS": "T24 trending high",
  "REQUESTED_BY": "assistant"
}
```

A part requisition requires `REFERENCE`, `STORE`, and at least one line with a known part and a positive integer quantity. `ASSET` is optional and a line's `UOM` defaults to the part's unit. Example body for `POST /partrequisitions`.

```json
{
  "REFERENCE": "draft-124",
  "STORE": "main",
  "LINES": [{"PART": {"ID": "P-HPC-01"}, "QUANTITY": 2, "UOM": "each"}],
  "REASON": "Replace worn seal"
}
```

On either POST, send the draft ID in the optional `Idempotency-Key` header and in `REFERENCE`. A new record returns 201. A repeated key on the same endpoint returns the original record with 200. The reference lookup works independently of the header.

## Failure switches

Set `MOCK_HEXAGON_MODE` before starting the process. State resets on restart.

| Mode | Behavior after authentication |
| --- | --- |
| `normal` | Default behavior |
| `down` | Returns 503 without processing the request |
| `slow` | Waits four seconds before processing the request, past the planned three-second client timeout |
| `lost-reply` | Saves each new POST, then returns 502 to simulate an unusable reply. GETs still work and a replay of an honored idempotency key returns the saved record |

Use `MOCK_HEXAGON_MODE=lost-reply MOCK_HEXAGON_IGNORE_IDEMPOTENCY=1 make mock-hexagon` to test reference recovery when the server ignores the header. In that mode, find the saved record with `GET /references` before deciding whether to submit again.

## Assumptions and public sources

- Hexagon documents collection and single-record GETs, record creation via POST, and API-key auth among its authentication options. The mock uses one local key, short routes, uppercase JSON, nested codes, plain collection arrays, simple filters, and a single site. These are mock conventions. The vendor guide documents its own headers, organization-aware IDs, and response structure. [HxGN EAM REST Web Services](https://docs.hexagonali.com/api/khub/documents/MmP3HEXid3DhIBwLBvsZXg/content)
- Hexagon lists work requests and part requisitions in its approval workflow documentation. The mock files requests and requisitions with synthetic IDs and simplified statuses. Release, scheduling, fulfilment, and closing are outside the mock API. [HxGN EAM Approval Workflows](https://docs.hexagonali.com/api/khub/documents/T6er5cULKOMcxXPI9Jxjew/content)
- The mock's reference lookup, idempotency header, and failure modes are project-defined behavior. Tests against this server verify the adapter's handling of those assumptions. A production deployment would need verification against its own API and configuration.
- Startup builds fresh fixtures from the same seed as the SQLite demo in a temporary directory. Work order comments use shorthand and typos with the same maintenance facts. Seeded failure codes are empty. Submitted records and idempotency keys live in memory for the life of the process.
