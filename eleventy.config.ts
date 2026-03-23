import type { UserConfig } from '@11ty/eleventy'

// noinspection JSUnusedGlobalSymbols
export default function (eleventyConfig: UserConfig) {
  eleventyConfig.addPassthroughCopy({ public: '/' })
  eleventyConfig.addPassthroughCopy({ '_data/pins.json': 'pins.json' })
  eleventyConfig.addPassthroughCopy({
    'node_modules/@fontsource-variable/mona-sans/files/mona-sans-latin-wght-normal.woff2':
      'fonts/mona-sans-normal.woff2',
    'node_modules/@fontsource-variable/mona-sans/files/mona-sans-latin-wght-italic.woff2':
      'fonts/mona-sans-italic.woff2',
  })
}

// noinspection JSUnusedGlobalSymbols
export const config = {
  dir: {
    input: '.',
    includes: '_includes',
    data: '_data',
    output: 'dist',
  },
  htmlTemplateEngine: 'liquid',
  markdownTemplateEngine: 'liquid',
  templateFormats: ['liquid', 'md'],
}
