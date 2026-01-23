"""
====================================

StockIt Image Scraper API

====================================

A Flask-based REST API optimized, aggregates images from multiple stock photo platforms with zero caching.

Features:
- Multi-source image search (Unsplash, Pexels, Pixabay)
- Format conversion (JPEG, PNG, WebP)
- Orientation and quality filters
- Generic URL scraping
- Cloudflare/WAF bypass

Version: 1.0.0
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from bs4 import BeautifulSoup
import cloudscraper
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
import urllib.parse
import random
import math

DEFAULT_SEARCH_QUERIES = [
  # Nature
  'nature', 'forest', 'mountains', 'waterfall', 'ocean', 'desert', 
  'sunset', 'sunrise', 'wildlife', 'macro nature',

  # Technology
  'technology', 'futuristic tech', 'artificial intelligence', 
  'robotics', 'cyberpunk', 'data center', 'coding setup',
  'circuit board', 'space technology',

  # People
  'people', 'portrait', 'street photography', 'candid people',
  'business portrait', 'fashion portrait', 'silhouette person',
  'emotional portrait',

  # Architecture
  'architecture', 'modern architecture', 'brutalist architecture',
  'futuristic buildings', 'interior design', 'skyscraper',
  'historical architecture', 'minimal architecture',

  # Urban & City
  'urban', 'cityscape', 'night city', 'street photography',
  'urban minimal', 'city lights', 'metro station',

  # Landscape
  'landscape', 'mountain landscape', 'coastal landscape',
  'aerial landscape', 'foggy landscape', 'rural landscape',

  # Abstract & Minimal
  'abstract', 'geometric abstract', 'abstract art',
  'minimal', 'minimal wallpaper', 'minimal design',
  'gradient background', 'line art',

  # Wallpapers
  'wallpaper', '4k wallpaper', 'desktop wallpaper',
  'mobile wallpaper', 'dark wallpaper', 'amoled wallpaper'
]

# ==========================================
# CONFIGURATION CONSTANTS
# ==========================================

# Scraping Constraints
TIMEOUT_SECONDS = 10
GENERIC_SCRAPE_TIMEOUT = 9.0      # Stop generic scrape after 9s
THREAD_POOL_TIMEOUT = 8.0         # Max time for all threads
THREAD_CHECK_TIMEOUT = 8.5        # Stop collecting threads after 8.5s
THREAD_RESULT_TIMEOUT = 1.0       # Timeout per thread result
REQUEST_TIMEOUT = 4               # Individual request timeout
MAX_RETRIES = 1                   # Max retries per request
SCRAPER_DELAY = 0.5               # Delay between requests
MAX_WORKERS = 6                   # Thread pool size

# Pagination & Limits
DEFAULT_LIMIT = 30
MAX_LIMIT = 200
PER_PAGE_DEFAULT = 30
MAX_PAGES_GENERIC = 3
MAX_PAGES_PER_SOURCE = 2
GENERIC_PAGE_SIZE = 20
DEFAULT_LIMIT_GENERIC = 50

# Settings
DEFAULT_QUALITY = 90
MAX_QUALITY = 100
MIN_QUALITY = 1
ORIENTATION_MAP = {'p': 'portrait', 'l': 'landscape', 's': 'square'}
BROWSER_CONFIG = {'browser': 'chrome', 'platform': 'windows', 'desktop': True}
SUPPORTED_IMAGE_FORMATS = ['png', 'webp', 'jpg', 'jpeg']
USER_AGENT = 'Mozilla/5.0'

# Source Specifics
PEXELS_HI_RES_SUFFIX = '?auto=compress&cs=tinysrgb&w=1600'
PIXABAY_REPLACE_PAIRS = [('_340', '_1280'), ('_640', '_1280')]

# Skip Keywords
SKIP_KEYWORDS = [
    'profile', '/user/', 'avatar', 'favicon', 'logo', 'icon', 
    'tracker', 'blank.gif', '_96x96', '_48x48'
]

# Cache Control
CACHE_CONTROL_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Surrogate-Control": "no-store",
    "X-Edge-Cache": "BYPASS",
    "CDN-Cache-Control": "no-store"
}

# ==========================================
# APPLICATION SETUP
# ==========================================

app = Flask(__name__)

# CORS configuration - allow all origins for maximum compatibility
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "max_age": 0  # No preflight caching
    }
})

@app.after_request
def prevent_caching(response):
    """
    CRITICAL: Prevent ALL caching at every level.
    This ensures fresh data on every request, bypassing:
    - Browser cache
    - CDN cache (Edge Network)
    - Proxy cache
    - Service worker cache
    """
    for key, value in CACHE_CONTROL_HEADERS.items():
        response.headers[key] = value
    
    # Add timestamp to force uniqueness
    response.headers["X-Timestamp"] = str(time.time())
    
    return response

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with JSON response."""
    return jsonify({
        "error": "Internal Server Error",
        "details": str(error),
        "timestamp": time.time()
    }), 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors with JSON response."""
    return jsonify({
        "error": "Endpoint not found",
        "details": str(error),
        "timestamp": time.time()
    }), 404

@app.errorhandler(504)
def timeout_error(error):
    """Handle timeout errors."""
    return jsonify({
        "error": "Request timeout",
        "details": f"Operation exceeded {GENERIC_SCRAPE_TIMEOUT} second limit. Try reducing 'lim' parameter.",
        "timestamp": time.time()
    }), 504


# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def get_scraper():
    """
    Create cloudscraper instance to bypass Cloudflare/WAF.
    Each call creates a fresh instance for thread safety.
    """
    return cloudscraper.create_scraper(
        browser=BROWSER_CONFIG,
        delay=SCRAPER_DELAY  # Reduced for speed
    )


def fetch_with_scraper(scraper, url, headers=None, retries=MAX_RETRIES):
    """
    Fetch URL with minimal retries and aggressive timeout.
    
    Args:
        scraper: Cloudscraper instance
        url: Target URL
        headers: Optional HTTP headers
        retries: Number of retry attempts
    
    Returns:
        Response object or None on failure
    """
    for i in range(retries):
        try:
            # Aggressive timeout
            r = scraper.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            
            if r.status_code == 200:
                print(f"✓ {url[:60]}... ({len(r.text)} bytes)")
                return r
            
            print(f"✗ [{r.status_code}] {url[:60]}...")
            
            # Skip retry on rate limiting (save time)
            if r.status_code in [403, 429]:
                return None
                
        except Exception as e:
            print(f"✗ Error: {url[:60]}... - {str(e)[:30]}")
            return None
    
    return None


def standardize_result(source, source_id, url, thumb, alt, base_url, width=0, height=0, 
                       start_color=None, photographer_name="Unknown", photographer_url=None, 
                       page_url=None, tags=None, ext=None, quality=90):
    """
    Normalize image data into consistent format across all sources.
    Generates conversion URLs dynamically to prevent caching.
    
    Args:
        source: Platform name
        source_id: Unique identifier
        url: Full resolution image URL
        thumb: Thumbnail URL
        alt: Alt text
        base_url: API base URL for conversion endpoints
        width/height: Dimensions
        start_color: Dominant color (hex)
        photographer_name: Author name
        photographer_url: Author profile
        page_url: Image page URL
        tags: List of tags
        ext: Desired format (triggers conversion URL)
        quality: JPEG/WebP quality (1-100)
    
    Returns:
        Standardized image dictionary
    """
    final_url = url
    
    # Generate conversion URL with cache-busting timestamp
    if ext and ext.lower() in SUPPORTED_IMAGE_FORMATS:
        encoded_url = urllib.parse.quote(url)
        cache_buster = int(time.time() * 1000)  # Millisecond timestamp
        final_url = f"{base_url}/convert?url={encoded_url}&ext={ext}&quality={quality}&_t={cache_buster}"

    return {
        "id": f"{source}_{source_id}",
        "source": source,
        "url": final_url,
        "original_url": url,
        "thumb": thumb,
        "alt": alt or f"{source.capitalize()} Image",
        "metadata": {
            "width": width,
            "height": height,
            "format": ext if ext else "original",
            "color": start_color
        },
        "author": {
            "name": photographer_name,
            "url": photographer_url or page_url
        },
        "tags": tags or [],
        "timestamp": int(time.time())  # Add timestamp to each result
    }


# ==========================================
# SOURCE-SPECIFIC SCRAPERS
# ==========================================

def scrape_unsplash_page(query, page, base_url, filters=None, ext=None, quality=DEFAULT_QUALITY):
    """
    Scrape Unsplash via internal NAPI (fastest, most reliable).
    """
    scraper = get_scraper()
    
    try:
        filters = filters or {}
        order_by = 'latest' if filters.get('order') == 'latest' else 'relevant'
        orientation = filters.get('orientation', '')
        if orientation == 'square':
            orientation = 'squarish'

        # Build API request with cache-busting
        params = {
            "query": query,
            "per_page": PER_PAGE_DEFAULT,
            "page": page,
            "orientation": orientation,
            "order_by": order_by,
            "_t": int(time.time() * 1000)  # Cache buster
        }
        query_string = urllib.parse.urlencode({k: v for k, v in params.items() if v})
        api_url = f"https://unsplash.com/napi/search/photos?{query_string}"
        
        r = fetch_with_scraper(scraper, api_url)
        if not r:
            return []
        
        results = []
        for item in r.json().get('results', []):
            try:
                user = item.get('user', {})
                urls = item.get('urls', {})
                
                results.append(standardize_result(
                    source="unsplash",
                    source_id=item['id'],
                    url=urls.get('regular', urls.get('full')),
                    thumb=urls.get('small', urls.get('thumb')),
                    alt=item.get('alt_description'),
                    base_url=base_url,
                    width=item.get('width'),
                    height=item.get('height'),
                    start_color=item.get('color'),
                    photographer_name=user.get('name'),
                    photographer_url=user.get('links', {}).get('html'),
                    tags=[t.get('title') for t in item.get('tags', [])][:3],
                    ext=ext,
                    quality=quality
                ))
            except:
                continue
        
        return results
        
    except Exception as e:
        print(f"Unsplash error: {e}")
        return []


def scrape_pexels_page(query, page, base_url, filters=None, ext=None, quality=DEFAULT_QUALITY):
    """
    Scrape Pexels via HTML parsing.
    Optimized for speed with minimal processing.
    """
    scraper = get_scraper()
    
    try:
        params = {
            "page": page,
            "_t": int(time.time() * 1000)  # Cache buster
        }
        if filters and filters.get('orientation'):
            params["orientation"] = filters.get('orientation')
            
        url = f"https://www.pexels.com/search/{query}/?{urllib.parse.urlencode(params)}"
        r = fetch_with_scraper(scraper, url)
        
        if not r:
            return []
        
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        
        for article in soup.find_all('article'):
            try:
                img = article.find('img')
                if not img:
                    continue
                
                img_src = img.get('src') or img.get('data-src')
                if not img_src:
                    continue
                
                # Fast filter
                if any(kw in img_src for kw in SKIP_KEYWORDS):
                    continue
                
                # Convert to high-res
                hi_res = img_src.split('?')[0] + PEXELS_HI_RES_SUFFIX if '?' in img_src else img_src
                
                photo_id = article.get('data-photo-modal-medium-id') or random.randint(100000, 999999)

                results.append(standardize_result(
                    source="pexels",
                    source_id=photo_id,
                    url=hi_res,
                    thumb=img_src,
                    alt=img.get('alt', 'Pexels Image'),
                    base_url=base_url,
                    photographer_name="Pexels Contributor",
                    ext=ext,
                    quality=quality
                ))
            except:
                continue
        
        return results
        
    except Exception as e:
        print(f"Pexels error: {e}")
        return []


def scrape_pixabay_page(query, page, base_url, filters=None, ext=None, quality=DEFAULT_QUALITY):
    """
    Scrape Pixabay via HTML parsing.
    Fast filtering to stay within timeout.
    """
    scraper = get_scraper()
    
    try:
        params = {
            "pagi": page,
            "_t": int(time.time() * 1000)  # Cache buster
        }
        if filters:
            if filters.get('orientation') == 'landscape':
                params['orientation'] = 'horizontal'
            elif filters.get('orientation') == 'portrait':
                params['orientation'] = 'vertical'

        url = f"https://pixabay.com/images/search/{query}/?{urllib.parse.urlencode(params)}"
        r = fetch_with_scraper(scraper, url)
        
        if not r:
            return []
        
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        
        for img in soup.find_all('img'):
            try:
                src = img.get('src') or img.get('data-src')
                
                # Fast filter with single check
                if not src or any(kw in src for kw in SKIP_KEYWORDS):
                    continue

                # Quick resolution upgrade
                hi_res = src
                for old, new in PIXABAY_REPLACE_PAIRS:
                    hi_res = hi_res.replace(old, new)
                
                results.append(standardize_result(
                    source="pixabay",
                    source_id=random.randint(100000, 999999),
                    url=hi_res,
                    thumb=src,
                    alt=img.get('alt', 'Pixabay Image'),
                    base_url=base_url,
                    photographer_name="Pixabay Contributor",
                    ext=ext,
                    quality=quality
                ))
            except:
                continue
        
        return results
        
    except Exception as e:
        print(f"Pixabay error: {e}")
        return []


def scrape_generic_url(target_url, base_url, ext=None, limit=DEFAULT_LIMIT_GENERIC):
    """
    Scrape images from generic URL with pagination.
    AGGRESSIVE timeout management.
    """
    scraper = get_scraper()
    all_results = []
    seen_urls = set()
    
    # STRICT limit for timeout
    pages_to_try = min(MAX_PAGES_GENERIC, math.ceil(limit / GENERIC_PAGE_SIZE))
    current_url = target_url
    
    start_time = time.time()
    
    for page_num in range(1, pages_to_try + 1):
        # CRITICAL: Stop if approaching timeout (1s buffer for response)
        if time.time() - start_time > GENERIC_SCRAPE_TIMEOUT:
            print("⚠ Timeout approaching, stopping scrape")
            break
            
        if len(all_results) >= limit:
            break
        
        try:
            print(f"Page {page_num}: {current_url[:60]}...")
            
            if not current_url.startswith(('http://', 'https://')):
                current_url = 'https://' + current_url

            r = fetch_with_scraper(scraper, current_url)
            if not r:
                break
            
            soup = BeautifulSoup(r.text, 'html.parser')

            # Fast extraction - preloads first
            for pl in soup.find_all('link', attrs={'rel': 'preload', 'as': 'image'}):
                href = pl.get('href')
                if href and href not in seen_urls:
                    full_url = urllib.parse.urljoin(current_url, href)
                    seen_urls.add(full_url)
                    
                    all_results.append(standardize_result(
                        source="external",
                        source_id=random.randint(1000, 999999),
                        url=full_url,
                        thumb=full_url,
                        alt="Preloaded Image",
                        base_url=base_url,
                        ext=ext
                    ))

            # IMG tags
            for img in soup.find_all('img'):
                img_url = (img.get('data-src') or img.get('data-original') or 
                          img.get('data-lazy') or img.get('src'))
                
                if not img_url or len(img_url) < 5 or 'data:image' in img_url:
                    continue
                
                full_url = urllib.parse.urljoin(current_url, img_url)
                
                # Fast skip
                if full_url in seen_urls or any(kw in full_url for kw in SKIP_KEYWORDS):
                    continue
                
                seen_urls.add(full_url)

                all_results.append(standardize_result(
                    source="external",
                    source_id=random.randint(100000, 999999),
                    url=full_url,
                    thumb=full_url,
                    alt=img.get('alt', 'External Image'),
                    base_url=base_url,
                    photographer_name=urllib.parse.urlparse(target_url).netloc,
                    ext=ext
                ))

            # Simple pagination
            next_link = None
            for selector in ['a[rel="next"]', '.pagination a:last-child', 'a.next']:
                try:
                    link = soup.select_one(selector)
                    if link and link.get('href'):
                        next_link = link.get('href')
                        break
                except:
                    pass

            if next_link:
                current_url = urllib.parse.urljoin(current_url, next_link)
            else:
                break  # No pagination found, stop
                    
        except Exception as e:
            print(f"Generic error: {e}")
            break

    print(f"✓ Scraped {len(all_results)} images in {time.time()-start_time:.2f}s")
    return all_results[:limit]


# ==========================================
# ORCHESTRATION
# ==========================================

def get_images_threaded(query, limit, base_url, filters=None, ext=None, quality=DEFAULT_QUALITY, 
                       sources=['unsplash', 'pexels', 'pixabay']):
    """
    Concurrent scraping with STRICT timeout management.
    """
    all_results = []
    
    # AGGRESSIVE limits
    pages_per_source = MAX_PAGES_PER_SOURCE
    
    print(f"🔍 Query: '{query}' | Target: {limit} | Pages/source: {pages_per_source}")
    
    futures = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for page in range(1, pages_per_source + 1):
            if 'unsplash' in sources:
                futures.append(executor.submit(scrape_unsplash_page, query, page, 
                                              base_url, filters, ext, quality))
            if 'pexels' in sources:
                futures.append(executor.submit(scrape_pexels_page, query, page, 
                                              base_url, filters, ext, quality))
            if 'pixabay' in sources:
                futures.append(executor.submit(scrape_pixabay_page, query, page, 
                                              base_url, filters, ext, quality))
        
        # Collect with timeout awareness
        for future in as_completed(futures, timeout=THREAD_POOL_TIMEOUT):
            try:
                # Check if approaching timeout
                if time.time() - start_time > THREAD_CHECK_TIMEOUT:
                    print("⚠ Timeout imminent, stopping collection")
                    break
                    
                res = future.result(timeout=THREAD_RESULT_TIMEOUT)
                if res:
                    print(f"✓ Thread: +{len(res)} results")
                    all_results.extend(res)
            except Exception as e:
                print(f"✗ Thread error: {str(e)[:50]}")
    
    elapsed = time.time() - start_time
    print(f"✓ Completed in {elapsed:.2f}s | {len(all_results)} total results")
    
    random.shuffle(all_results)
    return all_results[:limit]


# ==========================================
# API ENDPOINTS
# ==========================================

@app.route('/')
def home():
    """
    API documentation endpoint.
    Returns index.html if available.
    """
    try:
        return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))
    except Exception as e:
        return jsonify({
            "api": "StockIt Image Scraper API",
            "status": "operational",
            "error": "index.html not found",
            "details": str(e)
        })


@app.route('/search')
def search():
    """
    Main search endpoint - all sources.
    Cache-busting enforced at every level.
    """
    query = request.args.get('q')
    if not query:
        return jsonify({
            'error': 'Missing required parameter: q',
            'timestamp': time.time()
        }), 400
    
    return search_handler(query)


@app.route('/all')
def all_images():
    """Random topic search if no query."""
    query = request.args.get('q', random.choice(DEFAULT_SEARCH_QUERIES))
    return search_handler(query)


@app.route('/unsplash')
def unsplash_images():
    """Unsplash-only search."""
    query = request.args.get('q', random.choice(DEFAULT_SEARCH_QUERIES))
    return search_handler(query, sources=['unsplash'])


@app.route('/pexels')
def pexels_images():
    """Pexels-only search."""
    query = request.args.get('q', random.choice(DEFAULT_SEARCH_QUERIES))
    return search_handler(query, sources=['pexels'])


@app.route('/pixabay')
def pixabay_images():
    """Pixabay-only search."""
    query = request.args.get('q', random.choice(DEFAULT_SEARCH_QUERIES))
    return search_handler(query, sources=['pixabay'])


def search_handler(query=None, sources=['unsplash', 'pexels', 'pixabay']):
    """
    Shared search logic with cache prevention.
    Returns JSON with cache-busting headers.
    """
    if not query:
        query = request.args.get('q')
        if not query:
            return jsonify({
                'error': 'Missing required parameter: q',
                'timestamp': time.time()
            }), 400
    
    # Parse params with safe limits
    try:
        limit = min(int(request.args.get('lim', DEFAULT_LIMIT)), MAX_LIMIT)
    except:
        limit = DEFAULT_LIMIT
    
    try:
        quality = min(max(int(request.args.get('quality', DEFAULT_QUALITY)), MIN_QUALITY), MAX_QUALITY)
    except:
        quality = DEFAULT_QUALITY
    
    ext = request.args.get('ext')
    
    # Orientation mapping
    orientation_map = ORIENTATION_MAP
    orientation = request.args.get('orientation', '').lower()
    orientation = orientation_map.get(orientation, orientation)
    
    order = request.args.get('order')
    
    # Get base URL (important for conversion links)
    base_url = request.host_url.rstrip('/')
    
    # Execute search
    results = get_images_threaded(
        query=query,
        limit=limit,
        base_url=base_url,
        filters={'orientation': orientation, 'order': order},
        ext=ext,
        quality=quality,
        sources=sources
    )
    
    # Return with cache-busting
    return jsonify({
        'count': len(results),
        'query': query,
        'format_requested': ext,
        'sources': sources,
        'results': results,
        'timestamp': int(time.time()),
        'cache_policy': 'no-store'
    })


@app.route('/url')
def fetch_from_url():
    """
    Scrape custom URL with strict timeout.
    """
    target_url = request.args.get('q')
    if not target_url:
        return jsonify({
            'error': 'Missing required parameter: q (target URL)',
            'timestamp': time.time()
        }), 400
    
    try:
        limit = min(int(request.args.get('lim', DEFAULT_LIMIT_GENERIC)), MAX_LIMIT)  # Cap for timeout
    except:
        limit = DEFAULT_LIMIT_GENERIC
    
    ext = request.args.get('ext')
    base_url = request.host_url.rstrip('/')
    
    results = scrape_generic_url(target_url, base_url, ext, limit)
    
    return jsonify({
        'count': len(results),
        'source_url': target_url,
        'format_requested': ext,
        'results': results,
        'timestamp': int(time.time()),
        'cache_policy': 'no-store'
    })


@app.route('/convert')
def convert():
    """
    Real-time image format conversion.
    """
    url = request.args.get('url')
    ext = request.args.get('ext', 'jpg').lower()
    
    try:
        quality = min(max(int(request.args.get('quality', DEFAULT_QUALITY)), MIN_QUALITY), MAX_QUALITY)
    except:
        quality = DEFAULT_QUALITY
    
    if not url:
        return jsonify({
            'error': 'Missing required parameter: url',
            'timestamp': time.time()
        }), 400
    
    scraper = get_scraper()
    
    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Cache-Control': 'no-cache'  # Request fresh image
        }
        
        # Stream download for memory efficiency
        r = scraper.get(url, headers=headers, stream=True, timeout=THREAD_POOL_TIMEOUT)
        r.raise_for_status()
        
        # Load and convert
        img = Image.open(BytesIO(r.content))
        
        # JPEG requires RGB mode
        if ext in ['jpg', 'jpeg'] and img.mode in ['RGBA', 'P']:
            img = img.convert('RGB')
            
        output = BytesIO()
        
        # Format-specific optimization
        if ext in ['jpg', 'jpeg']:
            img.save(output, format='JPEG', quality=quality, optimize=True)
            mimetype = 'image/jpeg'
        elif ext == 'png':
            img.save(output, format='PNG', optimize=True)
            mimetype = 'image/png'
        elif ext == 'webp':
            img.save(output, format='WEBP', quality=quality, method=4)
            mimetype = 'image/webp'
        else:
            return jsonify({
                'error': 'Unsupported format. Use: jpg, png, or webp',
                'timestamp': time.time()
            }), 400
            
        output.seek(0)
        
        # Return with anti-cache headers
        response = send_file(output, mimetype=mimetype)
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        return jsonify({
            'error': f"Conversion failed: {str(e)}",
            'timestamp': time.time()
        }), 500


# ==========================================
# ENTRY POINT
# ==========================================

app = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)