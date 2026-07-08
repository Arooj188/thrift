import re

def analyze_item(category, times_worn, has_tears, description, tags, title=None, existing_listings=None):
    """AI Listing Assistant that improves descriptions, classifies categories, detects duplicates, and screens inappropriate text."""
    if category and category.lower() not in {'clothing', 'shoes', 'accessories', 'vintage', 'streetwear'}:
        normalized = category.strip().lower()
        if 'shoe' in normalized:
            category = 'Shoes'
        elif 'vintage' in normalized:
            category = 'Vintage'
        else:
            category = 'Clothing'

    if not category:
        category = 'Clothing'

    description_text = ' '.join(description.split()).strip()
    if not description_text:
        description_text = f"{title or 'A thoughtfully curated item'} listed under {category}."

    lower_has_tears = (has_tears or '').lower()
    summary_parts = []

    if 'tear' in lower_has_tears or 'stain' in lower_has_tears or 'hole' in lower_has_tears:
        summary_parts.append('Seller disclosed minor wear or surface flaws.')
    else:
        summary_parts.append('Seller reports clean condition with no major damage.')

    try:
        worn_count = int(times_worn)
    except (TypeError, ValueError):
        worn_count = 0

    if worn_count == 0:
        summary_parts.append('Item is in like-new condition with very little or no use.')
    elif worn_count <= 5:
        summary_parts.append('Lightly worn and maintained carefully.')
    else:
        summary_parts.append('Gently used with normal wear consistent with prior use.')

    improved_description = f"{description_text} {summary_parts[0]} {summary_parts[1]}"
    improved_description = re.sub(r'\s+', ' ', improved_description).strip()

    duplicate = False
    duplicate_reason = ''
    normalized_title = (title or '').strip().lower()
    normalized_description = description_text.lower()
    if existing_listings:
        for existing in existing_listings:
            existing_title = (existing.get('title') or '').strip().lower()
            existing_description = (existing.get('description') or '').strip().lower()
            if normalized_title and existing_title and normalized_title == existing_title:
                duplicate = True
                duplicate_reason = 'Exact title match found.'
                break
            if normalized_title and existing_title and normalized_title in existing_title:
                duplicate = True
                duplicate_reason = 'Similar title detected.'
                break
            if normalized_description and existing_description and normalized_description in existing_description:
                duplicate = True
                duplicate_reason = 'Description appears duplicated.'
                break

    unsafe_terms = ['offensive', 'illegal', 'prohibited', 'racist', 'hate', 'weapon']
    lower_content = ' '.join([normalized_title, normalized_description, (tags or '').lower()])
    inappropriate = any(term in lower_content for term in unsafe_terms)

    score = 100
    score -= min(30, worn_count * 3)
    if 'minor' in lower_has_tears or 'yes' in lower_has_tears:
        score -= 20
    if duplicate:
        score -= 20
    if inappropriate:
        score -= 30
    score = max(10, min(100, score))

    return {
        'score': score,
        'summary': improved_description,
        'category': category,
        'duplicate': duplicate,
        'duplicate_reason': duplicate_reason,
        'inappropriate': inappropriate,
    }
