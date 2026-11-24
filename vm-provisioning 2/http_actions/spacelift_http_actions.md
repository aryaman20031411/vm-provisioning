# Spacelift HTTP actions (Agent Studio)

Four actions, all on one connector:

- **Connector:** `spacelift`
- **Base URL:** `https://<your-account>.app.spacelift.io`
- **Auth:** none on the connector. Spacelift wants a short-lived JWT (it expires after 1 hour), so
  `spacelift_get_token` swaps your API key for a JWT, and the other three send it as a Bearer header.
- Every request is `POST /graphql` with header `Content-Type: application/json`.

How the stack is driven: it holds **every current VM request** in one environment variable,
`TF_VAR_vm_requests`. Each row is one VM; rows are separated by `;` and fields by `|`:

```
request_id|environment|vcpu|memory_gb|disk_gb|os_image|owner|hostname|lease_days|requester_email
```

To provision, Moveworks reads the list, adds a row, writes it back and triggers a run. To delete, it
removes a row and triggers a run. `none` means no VMs. Terraform reports what exists in one output,
`vm_inventory` (`request_id|hostname|ip|instance_id|requester_email|environment|instance_type|os_image`).

Create the API key in Spacelift: Organization settings -> API keys -> Create (secret type).
Give it a role with write access to the space that holds the `vm-provisioner` stack.

---

## 1. `spacelift_get_token`

No input args. The key goes straight into the body, so it never passes through the compound
action's data. This is fine for a demo; for production, use your tenant's credential store if its
connector auth supports a token exchange.

```json
{
  "query": "mutation($id: ID!, $secret: String!) { apiKeyUser(id: $id, secret: $secret) { jwt } }",
  "variables": { "id": "<API_KEY_ID>", "secret": "<API_KEY_SECRET>" }
}
```

Output used: `data.apiKeyUser.jwt`

---

## 2. `spacelift_get_stack`

Reads the current request list and the current inventory.

Input args: `jwt`, `stack_id`. Header: `Authorization: Bearer {{jwt}}`

```json
{
  "query": "query($stack: ID!) { stack(id: $stack) { id state config { id value } outputs { id value } } }",
  "variables": { "stack": "{{stack_id}}" }
}
```

Outputs used: `data.stack.config` (find `TF_VAR_vm_requests`) and `data.stack.outputs`
(find `vm_inventory`; its `value` is JSON-encoded, so it arrives wrapped in quotes).

---

## 3. `spacelift_apply_requests`

Writes the new list and triggers a tracked run. GraphQL runs the fields of a mutation one after
another, so the variable is saved before `runTrigger` fires.

Input args: `jwt`, `stack_id`, `vm_requests`. Header: `Authorization: Bearer {{jwt}}`

```json
{
  "query": "mutation($stack: ID!, $reqs: String!) { cfg: stackConfigAdd(stack: $stack, config: {id: \"TF_VAR_vm_requests\", value: $reqs, type: ENVIRONMENT_VARIABLE, writeOnly: false}) { id } run: runTrigger(stack: $stack) { id state } }",
  "variables": { "stack": "{{stack_id}}", "reqs": "{{vm_requests}}" }
}
```

Output used: `data.run.id`. The `|` and `;` format has no quotes in it, so it's safe to drop into
the JSON body.

---

## 4. `spacelift_get_run`

Input args: `jwt`, `stack_id`, `run_id`. Header: `Authorization: Bearer {{jwt}}`

```json
{
  "query": "query($stack: ID!, $run: ID!) { stack(id: $stack) { run(id: $run) { id state } outputs { id value } } }",
  "variables": { "stack": "{{stack_id}}", "run": "{{run_id}}" }
}
```

Outputs used: `data.stack.run.state` (`QUEUED`, `PREPARING`, `PLANNING`, `APPLYING`, `FINISHED`,
`FAILED`, ...) and `data.stack.outputs`.

---

## Test before wiring

1. Run `spacelift_get_token` and copy the JWT.
2. Run `spacelift_apply_requests` with
   `vm_requests = VMR-000001|dev|2|8|50|Ubuntu 22.04|test|dev-ubu-test-001|7|you@yourco.com`.
   A run should appear on the stack.
3. Run `spacelift_get_run` until `state` is `FINISHED`, then check `outputs` has a `vm_inventory` row.
4. Run `spacelift_apply_requests` again with `vm_requests = none`. The test VM should be destroyed.

GraphQL errors come back as HTTP 200 with an `errors` array, so check that first. If a field is
refused (`stackConfigAdd`, `runTrigger`, `config`, `run(id:)`, `outputs`), look it up in the schema in
Spacelift's API explorer. These were written from the docs and have not been run against a live account.
