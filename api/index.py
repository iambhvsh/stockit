"""

====================================
StockIt Image Scraper API
====================================

A Flask-based REST API optimized, aggregates images from multiple stock photo platforms with zero caching.
Features:

- Multi-source image search (Unsplash, Pixabay, StockSnap)
- Format conversion hints (CDN-based)
- Orientation and quality filters
- Cloudflare/WAF bypass

Version: 1.1.0
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from bs4 import BeautifulSoup
import cloudscraper
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
import urllib.parse
import random

DEFAULT_SEARCH_QUERIES = [
  'nature', 'forest', 'mountains', 'waterfall', 'ocean', 'desert', 'sunset', 'sunrise', 'wildlife', 'macro nature',
  'technology', 'futuristic tech', 'artificial intelligence', 'robotics', 'cyberpunk', 'data center', 'coding setup', 'circuit board', 'space technology',
  'people', 'portrait', 'street photography', 'candid people', 'business portrait', 'fashion portrait', 'silhouette person', 'emotional portrait',
  'architecture', 'modern architecture', 'brutalist architecture', 'futuristic buildings', 'interior design', 'skyscraper', 'historical architecture', 'minimal architecture',
  'urban', 'cityscape', 'night city', 'street photography', 'urban minimal', 'city lights', 'metro station',
  'landscape', 'mountain landscape', 'coastal landscape', 'aerial landscape', 'foggy landscape', 'rural landscape',
  'abstract', 'geometric abstract', 'abstract art', 'minimal', 'minimal wallpaper', 'minimal design', 'gradient background', 'line art',
  'wallpaper', '4k wallpaper', 'desktop wallpaper', 'mobile wallpaper', 'dark wallpaper', 'amoled wallpaper'
]

# ==========================================
# CONFIGURATION CONSTANTS
# ==========================================

# Scraping Constraints
THREAD_POOL_TIMEOUT = 8.0
THREAD_CHECK_TIMEOUT = 8.5
THREAD_RESULT_TIMEOUT = 1.0
REQUEST_TIMEOUT = 4
MAX_RETRIES = 2
SCRAPER_DELAY = 0.5
MAX_WORKERS = 6

# Pagination & Limits
DEFAULT_LIMIT = 30
MAX_LIMIT = 200
PER_PAGE_DEFAULT = 30
MAX_PAGES_PER_SOURCE = 2

# Settings
DEFAULT_QUALITY = 90
MAX_QUALITY = 100
MIN_QUALITY = 1
ORIENTATION_MAP = {'p': 'portrait', 'l': 'landscape', 's': 'square'}
BROWSER_CONFIG = {'browser': 'chrome', 'platform': 'windows', 'desktop': True}
SUPPORTED_IMAGE_FORMATS = ['png', 'webp', 'jpg', 'jpeg']
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0',
]

# Source Specifics
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

CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "max_age": 0
    }
})

@app.after_request
def prevent_caching(response):
    """CRITICAL: Prevent ALL caching at every level."""
    for key, value in CACHE_CONTROL_HEADERS.items():
        response.headers[key] = value
    response.headers["X-Timestamp"] = str(time.time())
    return response

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal Server Error",
        "details": str(error),
        "timestamp": time.time()
    }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "details": str(error),
        "timestamp": time.time()
    }), 404

@app.errorhandler(504)
def timeout_error(error):
    return jsonify({
        "error": "Request timeout",
        "details": "Operation exceeded time limit.",
        "timestamp": time.time()
    }), 504


# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def get_scraper():
    return cloudscraper.create_scraper(
        browser=BROWSER_CONFIG,
        delay=SCRAPER_DELAY
    )


def fetch_with_scraper(scraper, url, headers=None, retries=MAX_RETRIES):
    for i in range(retries):
        try:
            r = scraper.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                if i < retries - 1:
                    time.sleep(0.5 * (2 ** i))
                continue
            if r.status_code == 403:
                return None
        except Exception:
            if i < retries - 1:
                continue
            return None
    return None

def append_ext(url, ext, quality):
    if not ext or ext.lower() not in SUPPORTED_IMAGE_FORMATS:
        return url

    ext = ext.lower()
    if ext == 'jpeg':
        ext = 'jpg'

    try:
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        query['fm'] = ext
        if quality and ext in ['jpg', 'webp']:
            query['q'] = str(quality)
        new_query = urllib.parse.urlencode(query)
        new_url = urllib.parse.urlunparse(parsed._replace(query=new_query))
        return new_url
    except Exception:
        return url


def standardize_result(source, source_id, url, thumb, alt, width=0, height=0, 
                       start_color=None, photographer_name="Unknown", photographer_url=None, 
                       page_url=None, tags=None, ext=None, quality=90):
    final_url = append_ext(url, ext, quality)

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
        "timestamp": int(time.time())
    }


# ==========================================
# SOURCE-SPECIFIC SCRAPERS
# ==========================================

def scrape_unsplash_page(query, page, filters=None, ext=None, quality=DEFAULT_QUALITY):
    scraper = get_scraper()
    try:
        filters = filters or {}
        order_by = 'latest' if filters.get('order') == 'latest' else 'relevant'
        orientation = filters.get('orientation', '')
        if orientation == 'square':
            orientation = 'squarish'

        params = {
            "query": query,
            "per_page": PER_PAGE_DEFAULT,
            "page": page,
            "orientation": orientation,
            "order_by": order_by,
            "_t": int(time.time() * 1000)
        }
        query_string = urllib.parse.urlencode({k: v for k, v in params.items() if v})
        api_url = f"https://unsplash.com/napi/search/photos?{query_string}"

        headers = {
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': f'https://unsplash.com/s/photos/{urllib.parse.quote(query)}',
            'User-Agent': random.choice(USER_AGENTS),
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }
        
        r = fetch_with_scraper(scraper, api_url, headers=headers)
        if not r:
            return []
        
        results = []
        for item in r.json().get('results', []):
            if item.get('plus') or item.get('premium') or item.get('sponsorship'):
                continue

            try:
                user = item.get('user', {})
                urls = item.get('urls', {})
                results.append(standardize_result(
                    source="unsplash",
                    source_id=item['id'],
                    url=urls.get('regular', urls.get('full')),
                    thumb=urls.get('small', urls.get('thumb')),
                    alt=item.get('alt_description'),
                    width=item.get('width'),
                    height=item.get('height'),
                    start_color=item.get('color'),
                    photographer_name=user.get('name'),
                    photographer_url=user.get('links', {}).get('html'),
                    tags=[t.get('title') for t in item.get('tags', [])][:3],
                    ext=ext,
                    quality=quality
                ))
            except Exception:
                continue
        return results
    except Exception:
        return []


def scrape_pixabay_page(query, page, filters=None, ext=None, quality=DEFAULT_QUALITY):
    scraper = get_scraper()
    try:
        params = {
            "pagi": page,
            "_t": int(time.time() * 1000)
        }
        if filters:
            if filters.get('orientation') == 'landscape':
                params['orientation'] = 'horizontal'
            elif filters.get('orientation') == 'portrait':
                params['orientation'] = 'vertical'

        url = f"https://pixabay.com/images/search/{query}/?{urllib.parse.urlencode(params)}"
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://pixabay.com/',
            'User-Agent': random.choice(USER_AGENTS),
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Upgrade-Insecure-Requests': '1',
        }
        r = fetch_with_scraper(scraper, url, headers=headers)
        if not r:
            return []
        
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        
        for img in soup.find_all('img'):
            try:
                src = img.get('src') or img.get('data-src')
                if not src or any(kw in src for kw in SKIP_KEYWORDS):
                    continue

                hi_res = src
                for old, new in PIXABAY_REPLACE_PAIRS:
                    hi_res = hi_res.replace(old, new)
                
                results.append(standardize_result(
                    source="pixabay",
                    source_id=random.randint(100000, 999999),
                    url=hi_res,
                    thumb=src,
                    alt=img.get('alt', 'Pixabay Image'),
                    photographer_name="Pixabay Contributor",
                    ext=ext,
                    quality=quality
                ))
            except Exception:
                continue
        return results
    except Exception:
        return []


def scrape_stocksnap_page(query, page, filters=None, ext=None, quality=DEFAULT_QUALITY):
    scraper = get_scraper()
    try:
        url = f"https://stocksnap.io/search/{query}"
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://stocksnap.io/',
            'User-Agent': random.choice(USER_AGENTS),
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Upgrade-Insecure-Requests': '1',
        }
        r = fetch_with_scraper(scraper, url, headers=headers)
        
        if not r:
            return []
        
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        
        for item in soup.select('.photo-grid-item a'):
            try:
                img = item.find('img')
                if not img:
                    continue
                    
                src = img.get('src')
                if not src or ('cdn.stocksnap.io' not in src and 'generated.stocksnap.io' not in src):
                     continue

                href = item.get('href')
                photo_id = href.split('/')[-1] if href else random.randint(100000, 999999)
                hi_res = src.replace('/img-thumbs/280h/', '/img-thumbs/960w/')
                
                results.append(standardize_result(
                    source="stocksnap",
                    source_id=photo_id,
                    url=hi_res,
                    thumb=src,
                    alt=img.get('alt', 'StockSnap Image'),
                    photographer_name="StockSnap Author",
                    ext=ext,
                    quality=quality
                ))
            except Exception:
                continue
        return results
    except Exception:
        return []


# ==========================================
# ORCHESTRATION
# ==========================================

def get_images_threaded(query, limit, filters=None, ext=None, quality=DEFAULT_QUALITY, 
                       sources=['unsplash', 'pixabay', 'stocksnap']):
    all_results = []
    
    futures = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for page in range(1, MAX_PAGES_PER_SOURCE + 1):
            if 'unsplash' in sources:
                futures.append(executor.submit(scrape_unsplash_page, query, page, 
                                              filters, ext, quality))
            if 'pixabay' in sources:
                futures.append(executor.submit(scrape_pixabay_page, query, page, 
                                              filters, ext, quality))
            if 'stocksnap' in sources:
                futures.append(executor.submit(scrape_stocksnap_page, query, page, 
                                              filters, ext, quality))
        
        for future in as_completed(futures, timeout=THREAD_POOL_TIMEOUT):
            try:
                if time.time() - start_time > THREAD_CHECK_TIMEOUT:
                    break
                
                res = future.result(timeout=THREAD_RESULT_TIMEOUT)
                if res:
                    all_results.extend(res)
            except Exception:
                pass
    
    random.shuffle(all_results)
    return all_results[:limit]


# ==========================================
# API ENDPOINTS
# ==========================================

@app.route('/')
def home():
    try:
        return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))
    except Exception as e:
        return jsonify({
            "api": "StockIt Image Scraper API",
            "status": "operational",
            "error": "index.html not found",
            "details": str(e)
        })


@app.route('/demo')
def demo():
    try:
        # Go up one level from 'api' to root, then into 'public/demo'
        return send_file(os.path.join(os.path.dirname(__file__), '..', 'public', 'demo', 'index.html'))
    except Exception as e:
        return jsonify({
            "error": "demo/index.html not found",
            "details": str(e)
        }), 404


@app.route('/search')
def search():
    query = request.args.get('q')
    if not query:
        return aggregate_random_images(sources=['unsplash', 'pixabay', 'stocksnap'])
    return search_handler(query)


def aggregate_random_images(sources):
    try:
        limit = min(int(request.args.get('lim', DEFAULT_LIMIT)), MAX_LIMIT)
    except:
        limit = DEFAULT_LIMIT
    
    try:
        quality = min(max(int(request.args.get('quality', DEFAULT_QUALITY)), MIN_QUALITY), MAX_QUALITY)
    except:
        quality = DEFAULT_QUALITY
    
    ext = request.args.get('ext')
    orientation = request.args.get('orientation', '')
    order = request.args.get('order')
    
    aggregated_results = []
    used_topics = set()
    max_attempts = 15
    attempts = 0
    
    while len(aggregated_results) < limit and attempts < max_attempts:
        attempts += 1
        
        available_topics = [t for t in DEFAULT_SEARCH_QUERIES if t not in used_topics]
        if not available_topics:
            used_topics = set()
            available_topics = DEFAULT_SEARCH_QUERIES
            
        current_topic = random.choice(available_topics)
        used_topics.add(current_topic)
        
        needed = limit - len(aggregated_results)
        
        current_batch = get_images_threaded(
            query=current_topic,
            limit=needed,
            filters={'orientation': orientation, 'order': order},
            ext=ext,
            quality=quality,
            sources=sources
        )
        aggregated_results.extend(current_batch)
        
    random.shuffle(aggregated_results)
    final_results = aggregated_results[:limit]
    
    return jsonify({
        'count': len(final_results),
        'query': 'random',
        'topics_used': list(used_topics),
        'format_requested': ext,
        'sources': sources,
        'results': final_results,
        'timestamp': int(time.time()),
        'cache_policy': 'no-store'
    })


@app.route('/all')
def all_images():
    query = request.args.get('q')
    if query:
        return search_handler(query, sources=['unsplash', 'pixabay', 'stocksnap'])
    return aggregate_random_images(sources=['unsplash', 'pixabay', 'stocksnap'])


@app.route('/unsplash')
def unsplash_images():
    query = request.args.get('q')
    if query:
        return search_handler(query, sources=['unsplash'])
    return aggregate_random_images(sources=['unsplash'])


@app.route('/pixabay')
def pixabay_images():
    query = request.args.get('q')
    if query:
        return search_handler(query, sources=['pixabay'])
    return aggregate_random_images(sources=['pixabay'])


@app.route('/stocksnap')
def stocksnap_images():
    query = request.args.get('q')
    if query:
        return search_handler(query, sources=['stocksnap'])
    return aggregate_random_images(sources=['stocksnap'])


def search_handler(query=None, sources=['unsplash', 'pixabay', 'stocksnap']):
    if not query:
        return aggregate_random_images(sources)
    
    try:
        limit = min(int(request.args.get('lim', DEFAULT_LIMIT)), MAX_LIMIT)
    except:
        limit = DEFAULT_LIMIT
    
    try:
        quality = min(max(int(request.args.get('quality', DEFAULT_QUALITY)), MIN_QUALITY), MAX_QUALITY)
    except:
        quality = DEFAULT_QUALITY
    
    ext = request.args.get('ext')
    orientation = request.args.get('orientation', '').lower()
    orientation = ORIENTATION_MAP.get(orientation, orientation)
    order = request.args.get('order')
    
    results = get_images_threaded(
        query=query,
        limit=limit,
        filters={'orientation': orientation, 'order': order},
        ext=ext,
        quality=quality,
        sources=sources
    )
    
    return jsonify({
        'count': len(results),
        'query': query,
        'format_requested': ext,
        'sources': sources,
        'results': results,
        'timestamp': int(time.time()),
        'cache_policy': 'no-store'
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
