// Runs resolveSettingsTab under node --experimental-strip-types.
// Reads a JSON array of raw tab param values from argv[2],
// prints a JSON array of resolved tab names.
// Driven by tests/unit/test_settings_tab_param.py.
import { resolveSettingsTab } from "../../frontend/src/lib/settingsTabParam.ts"

const inputs: (string | null)[] = JSON.parse(process.argv[2])
console.log(JSON.stringify(inputs.map((v) => resolveSettingsTab(v))))
