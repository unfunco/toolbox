import { cp, mkdir } from "fs/promises"

interface PinnedAction {
	action: string
	tag: string
	sha: string
	published_at: string
}

const pinsSource: { actions: PinnedAction[] } = await Bun.file("data/pins.json").json()

// Optimise: strip published_at, use compact tuples [action, sha, tag].
const pins: [string, string, string][] = pinsSource.actions.map(
	({ action, sha, tag }) => [action, sha, tag],
)

await mkdir("src/pins", { recursive: true })
await Bun.write(
	"src/pins/data.gen.ts",
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
