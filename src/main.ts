import pins from "./data.gen"

const input = document.querySelector<HTMLInputElement>("#search")!
const results = document.querySelector<HTMLElement>("#results")!

function pin(action: string, sha: string, tag: string): string {
	return `uses: ${action}@${sha} # ${tag}`
}

function render(matches: (typeof pins)[number][]) {
	results.innerHTML = matches
		.map((m) => {
			const text = pin(m[0], m[1], m[2])
			return `<button class="pin" title="Copy to clipboard">${text}</button>`
		})
		.join("")
}

input.addEventListener("input", () => {
	const query = input.value.toLowerCase()
	if (!query) {
		results.innerHTML = ""
		return
	}
	render(pins.filter(([action]) => action.toLowerCase().includes(query)))
})

results.addEventListener("click", async (e) => {
	const target = e.target as HTMLElement
	if (!target.classList.contains("pin")) return
	await navigator.clipboard.writeText(target.textContent!)
	target.classList.add("copied")
	setTimeout(() => target.classList.remove("copied"), 1500)
})
