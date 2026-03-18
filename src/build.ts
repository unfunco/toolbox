import { cp, mkdir } from "fs/promises"

interface Action {
	action: string
	tag: string
	sha: string
	published_at: string
}

const state: { actions: Action[] } = await Bun.file("state.json").json()

// Optimise: strip published_at, use compact tuples [action, sha, tag].
const pins: [string, string, string][] = state.actions.map(
	({ action, sha, tag }) => [action, sha, tag],
)

await Bun.write(
	"src/data.gen.ts",
	`export default ${JSON.stringify(pins)} as const;\n`,
)

await mkdir("dist", { recursive: true })

const result = await Bun.build({
	entrypoints: ["src/main.ts"],
	outdir: "dist",
	minify: true,
})

if (!result.success) {
	console.error("Build failed:", result.logs)
	process.exit(1)
}

await cp("src/index.html", "dist/index.html")
