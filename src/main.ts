import pins from './pins/data.gen'

const input = document.querySelector<HTMLInputElement>('#search')!
const results = document.querySelector<HTMLElement>('#results')!

function pin(action: string, sha: string, tag: string): string {
  return `uses: ${action}@${sha} # ${tag}`
}

function render(matches: (typeof pins)[number][]) {
  results.innerHTML = matches
    .map((m) => {
      const text = pin(m[0], m[1], m[2])
      return `<button class="pin cursor-pointer break-all rounded-md border border-border bg-canvas-subtle px-3 py-2 text-left font-mono text-xs text-fg transition-colors" title="Copy to clipboard">${text}</button>`
    })
    .join('')
}

input.addEventListener('input', () => {
  const query = input.value.toLowerCase()
  if (!query) {
    results.innerHTML = ''
    return
  }
  render(pins.filter(([action]) => action.toLowerCase().includes(query)))
})

results.addEventListener('click', async (e) => {
  const target = e.target as HTMLElement
  if (!target.classList.contains('pin')) return
  await navigator.clipboard.writeText(target.textContent!)
  target.classList.add('copied')
  setTimeout(() => target.classList.remove('copied'), 1500)
})

document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document
      .querySelectorAll('.tab-btn')
      .forEach((b) => b.classList.remove('selected'))
    document
      .querySelectorAll('.tab-content')
      .forEach((c) => c.classList.remove('active'))

    btn.classList.add('selected')
    const targetId = btn.getAttribute('data-target')!
    document.getElementById(targetId)!.classList.add('active')
  })
})
