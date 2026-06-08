# Blog Inbox — How to drop a new blog post

This is where you drop new blog content. Claude picks it up from here when you say "publish my new blog".

## What to drop

For each new blog post, put **two files** in this folder:

1. `your-post-slug.md` — the blog body in Markdown (text format). You can write in Word and save-as-markdown, or just paste plain text.
2. `your-post-slug.jpg` (or `.png`/`.webp`) — the cover photo. Square or 16:9. Min 1200px wide for clean previews.

The two files must share the same base name. Example:
- `inflation-running-hotter.md`
- `inflation-running-hotter.jpg`

That's it. Don't worry about folder structure, JSON files, or HTML — Claude generates everything.

## What Claude does when you say "publish my new blog"

1. Reads `your-post-slug.md`
2. Runs the categorizer (`../_tools/categorize.py`) on the title + body
3. Suggests 1 of 4 topics: **Stock Market · Commodities · Macros · Geopolitics**
4. Shows you the suggestion with confidence score + keyword evidence
5. You confirm or override
6. Claude builds the full post page at `/blog/posts/your-post-slug/`
7. Appends to `posts.json` so the post shows up on `/blog/`
8. Adds URL to `sitemap.xml`
9. Deploys and auto-pings Bing + Yandex via IndexNow
10. Within 1–24 hours the post is in Google + Bing + ChatGPT + Perplexity index

## Markdown reminders

- `# Heading` becomes H2 in the post (the H1 is your title)
- `## Subheading` becomes H3
- `**bold**` for bold, `*italic*` for italic
- `[link text](https://url.com)` for links
- `> quote` for blockquotes
- `- item` lines for bullet lists
- Blank line between paragraphs

## Workflow tl;dr

```
1. Drop two files in this folder
2. Tell Claude "publish my new blog"
3. Confirm the topic Claude suggests
4. Done — deployed in ~30 seconds
```
