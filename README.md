# StockIt Image Scraper API

A unified REST API that aggregates free stock images from multiple platforms (Unsplash, Pixabay, StockSnap) with built-in format conversion, quality optimization, and filtering capabilities.

## Features

- **Multi-Source Aggregation**: Search across Unsplash, Pixabay, and StockSnap simultaneously
- **Format Conversion**: Convert images to PNG, JPG, or WebP on-the-fly via CDN hints
- **Quality Control**: Adjust compression quality (1-100) for optimized delivery
- **Smart Filtering**: Filter by orientation (portrait, landscape, square)
- **Concurrent Scraping**: Fast parallel requests with ThreadPoolExecutor
- **Zero Caching**: Fresh results on every request
- **Cloudflare Bypass**: Built-in cloudscraper for WAF/anti-bot protection

## Base URL

```
https://imgstcks.vercel.app
```

## API Endpoints

### 1. `/search` - Unified Search

Search across all platforms or get random curated images.

**Query Parameters:**
- `q` (string, required*): Search query (*optional - returns random images if omitted)
- `lim` (integer): Number of results (default: 30, max: 200)
- `ext` (string): Output format - `jpg`, `png`, `webp`
- `quality` (integer): Compression quality 1-100 (default: 90)
- `orientation` (string): Filter by orientation - `p` (portrait), `l` (landscape), `s` (square)
- `order` (string): Sort order - `latest` or `relevant`

**Example:**
```bash
curl "https://imgstcks.vercel.app/search?q=cyberpunk&lim=5&ext=webp&quality=80"
```

**Response:**
```json
{
  "count": 5,
  "query": "cyberpunk",
  "format_requested": "webp",
  "sources": ["unsplash", "pixabay", "stocksnap"],
  "results": [
    {
      "id": "unsplash_abc123",
      "source": "unsplash",
      "url": "https://images.unsplash.com/photo-xyz?fm=webp&q=80",
      "original_url": "https://images.unsplash.com/photo-xyz",
      "thumb": "https://images.unsplash.com/photo-xyz?w=400",
      "alt": "Cyberpunk cityscape at night",
      "metadata": {
        "width": 4000,
        "height": 2667,
        "format": "webp",
        "color": "#0a1929"
      },
      "author": {
        "name": "John Doe",
        "url": "https://unsplash.com/@johndoe"
      },
      "tags": ["cyberpunk", "neon", "city"],
      "timestamp": 1737648000
    }
  ],
  "timestamp": 1737648000,
  "cache_policy": "no-store"
}
```

### 2. `/all` - Random Curated Images

Fetches random images from curated topics across all platforms.

**Example:**
```bash
curl "https://imgstcks.vercel.app/all?lim=10&ext=png"
```

### 3. `/{source}` - Platform-Specific Endpoints

Query individual platforms directly or get random images from that platform.

**Available Sources:**
- `/unsplash` - Unsplash images only
- `/pixabay` - Pixabay images only
- `/stocksnap` - StockSnap images only

**Example:**
```bash
# Search Unsplash only
curl "https://imgstcks.vercel.app/unsplash?q=nature&lim=20"

# Get random Pixabay images
curl "https://imgstcks.vercel.app/pixabay?ext=webp"
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (format: `{source}_{source_id}`) |
| `source` | string | Origin platform (`unsplash`, `pixabay`, `stocksnap`) |
| `url` | string | Optimized image URL with format/quality params |
| `original_url` | string | Original image URL without modifications |
| `thumb` | string | Thumbnail URL for preview |
| `alt` | string | Alt text/description |
| `metadata.width` | integer | Image width in pixels |
| `metadata.height` | integer | Image height in pixels |
| `metadata.format` | string | Requested format |
| `metadata.color` | string | Dominant color (hex code) |
| `author.name` | string | Photographer/creator name |
| `author.url` | string | Photographer's profile URL |
| `tags` | array | Related tags/keywords |
| `timestamp` | integer | Unix timestamp of response |

## Deployment

### Deploy to Vercel

1. **Clone the repository:**
```bash
git clone https://github.com/iambhvsh/stockit
cd stockit-api
```

2. **Install Vercel CLI:**
```bash
pnpm i -g vercel
```

3. **Deploy:**
```bash
vercel
```

### Local Development

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Run the development server:**
```bash
python api/index.py
```

3. **Access the API:**
```
http://localhost:5000
```

## Configuration

Key constants in `api/index.py`:

```python
DEFAULT_LIMIT = 30          # Default number of results
MAX_LIMIT = 200            # Maximum results per request
DEFAULT_QUALITY = 90       # Default image quality
MAX_WORKERS = 6            # Concurrent thread workers
REQUEST_TIMEOUT = 4        # HTTP request timeout (seconds)
MAX_PAGES_PER_SOURCE = 2   # Pages to scrape per platform
```

## Architecture

- **Flask**: Lightweight WSGI web framework
- **CloudScraper**: Cloudflare/WAF bypass using browser fingerprinting
- **BeautifulSoup4**: HTML parsing for scraping
- **ThreadPoolExecutor**: Concurrent API requests
- **Flask-CORS**: Cross-origin resource sharing

## Caching Policy

The API implements aggressive no-cache headers to ensure fresh results:

```python
Cache-Control: no-store, no-cache, must-revalidate
Pragma: no-cache
Expires: 0
CDN-Cache-Control: no-store
```

## Limitations

- Maximum 200 results per request
- No API key required (public access)
- Premium/sponsored content filtered out
- Quality parameter only affects JPG/WebP formats

## Error Handling

The API returns standardized error responses:

```json
{
  "error": "Error type",
  "details": "Detailed error message",
  "timestamp": 1737648000
}
```

**Common HTTP Status Codes:**
- `200` - Success
- `404` - Endpoint not found
- `500` - Internal server error
- `504` - Request timeout

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is provided as-is for educational and personal use.

## Credits

Developed by **Bhavesh**

Images sourced from:
- [Unsplash](https://unsplash.com)
- [Pixabay](https://pixabay.com)
- [StockSnap](https://stocksnap.io)

---

**Note**: This API scrapes publicly available images. Always respect the licensing terms of the source platforms when using retrieved images.
