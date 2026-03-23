import { mkdir } from 'fs/promises'
import { $ } from 'bun'

interface PinnedAction {
  action: string
  tag: string
  sha: string
  published_at: string
}

const pinsSource: { actions: PinnedAction[] } =
  await Bun.file('data/pins.json').json()

// Optimise: strip published_at, use compact tuples [action, sha, tag].
const pins: [string, string, string][] = pinsSource.actions.map(
  ({ action, sha, tag }) => [action, sha, tag],
)

await mkdir('src/pins', { recursive: true })
await Bun.write(
  'src/pins/data.gen.ts',
  `export default ${JSON.stringify(pins)} as const;\n`,
)

await mkdir('_site', { recursive: true })

// Bundle client-side JavaScript with Bun.
const result = await Bun.build({
  entrypoints: ['src/main.ts'],
  outdir: '_site',
  minify: true,
})

if (!result.success) {
  console.error('Build failed:', result.logs)
  process.exit(1)
}

// Build HTML templates with Eleventy.
await $`bunx eleventy --quiet`

// Build CSS with Tailwind.
await $`bunx @tailwindcss/cli -i src/styles.css -o _site/styles.css --minify`
