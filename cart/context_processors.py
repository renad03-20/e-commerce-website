from .utils import get_cart_data

def cart_context(request):

    #! makes cart data available across all templates
    cart_data = get_cart_data(request)
    return {
        'cart_total_quantity': cart_data['total_quantity'],
        'cart_total_price': cart_data['total_price'],
        'cart_items': cart_data['items']
    }