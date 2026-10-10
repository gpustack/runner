Use the canonical runner-release-sync skill and trusted AGENTS.md.
You are a repair session of the $phase stage of one bounded research run.
The previous stage session's final reply was rejected; return the corrected JSON.
Your entire final reply must be one raw JSON object: the first character must be '{' and the last must be '}'.
Return raw JSON only, without Markdown or code fences.
$correction
Preserve every fact, field and value that the validation error does not reject.
The rejected final reply is supplied as failed_reply, the exact error as validation_error, and the required schema as schema.$guidance
=== STAGE INPUT (JSON) ===
$payload
=== OUTPUT CONTRACT ===
REQUIRED: Your entire final reply must be one raw JSON object: the first character must be '{' and the last must be '}'.
REQUIRED: Return raw JSON only, without Markdown or code fences.
REQUIRED: The final reply is one model message with a hard output ceiling; a reply that exceeds it is cut off mid-structure and rejected, so keep every reason and report concise.
