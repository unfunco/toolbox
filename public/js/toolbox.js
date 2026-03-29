// SPDX-FileCopyrightText: 2026 Daniel Morris <daniel@honestempire.com>
// SPDX-License-Identifier: MIT

const searchInput = document.querySelector('#search')
const results = document.querySelector('#results')
const status = document.querySelector('#search-status')

if (!(searchInput instanceof HTMLInputElement)) {
  throw new Error('Expected #search to be an input element')
}

if (!(results instanceof HTMLElement)) {
  throw new Error('Expected #results to exist')
}

if (!(status instanceof HTMLElement)) {
  throw new Error('Expected #search-status to exist')
}

const state = {
  pins: [],
}

function formatPin(pin) {
  return `uses: ${pin.action}@${pin.sha} # ${pin.tag}`
}

function setStatus(message, isError = false) {
  status.textContent = message
  status.classList.toggle('is-error', isError)
}

function renderEmpty(message) {
  const empty = document.createElement('p')
  empty.className = 'result-empty'
  empty.textContent = message
  results.replaceChildren(empty)
}

function createResult(pin) {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'pin-result'

  const copyText = formatPin(pin)
  button.dataset.copy = copyText

  const meta = document.createElement('div')
  meta.className = 'result-meta'

  const name = document.createElement('span')
  name.className = 'result-name'
  name.textContent = pin.action

  const tag = document.createElement('span')
  tag.className = 'result-tag'
  tag.textContent = pin.tag

  meta.append(name, tag)

  const code = document.createElement('code')
  code.className = 'result-code'
  code.textContent = copyText

  button.append(meta, code)
  return button
}

function renderResults(query) {
  const normalizedQuery = query.trim().toLowerCase()

  if (normalizedQuery.length === 0) {
    renderEmpty(`Start typing to search ${state.pins.length} pinned actions.`)
    setStatus('')
    return
  }

  const matches = state.pins
    .filter((pin) => pin.action.toLowerCase().includes(normalizedQuery))
    .slice(0, 40)

  if (matches.length === 0) {
    renderEmpty(`No pins match "${query.trim()}".`)
    setStatus(`No matches for "${query.trim()}".`)
    return
  }

  const fragment = document.createDocumentFragment()

  for (const pin of matches) {
    fragment.append(createResult(pin))
  }

  results.replaceChildren(fragment)

  const plural = matches.length === 1 ? '' : 'es'
  const suffix = matches.length === 40 ? ' Showing the first 40 matches.' : ''
  setStatus(`${matches.length} match${plural} for "${query.trim()}".${suffix}`)
}

async function loadPins() {
  const response = await fetch('pins.json', {
    headers: {
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to load pins.json: ${response.status}`)
  }

  const payload = await response.json()

  if (!payload || !Array.isArray(payload.actions)) {
    throw new Error('pins.json did not contain an actions array')
  }

  state.pins = payload.actions
  renderResults(searchInput.value)
}

searchInput.addEventListener('input', () => {
  renderResults(searchInput.value)
})

results.addEventListener('click', (event) => {
  const target = event.target

  if (!(target instanceof Element)) {
    return
  }

  const button = target.closest('button.pin-result')

  if (!(button instanceof HTMLButtonElement)) {
    return
  }

  const copyText = button.dataset.copy

  if (!copyText) {
    console.error('Selected pin result did not include copy text')
    setStatus('Copy failed because the selected result was incomplete.', true)
    return
  }

  navigator.clipboard.writeText(copyText).then(
    () => {
      button.classList.add('copied')
      setStatus(`Copied ${copyText}`)
      setTimeout(() => button.classList.remove('copied'), 1500)
    },
    (error) => {
      console.error('Failed to copy pin result', error)
      setStatus('Copy failed. Your browser blocked clipboard access.', true)
    },
  )
})

loadPins().catch((error) => {
  console.error('Failed to load pinned actions', error)
  renderEmpty('Pinned actions could not be loaded right now.')
  setStatus('Pinned actions could not be loaded. Refresh and try again.', true)
})
