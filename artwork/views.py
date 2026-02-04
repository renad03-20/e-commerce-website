from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from .models import Artwork, Category, Tag
from .forms import ArtworkForm, CustomRequestForm
from cart.models import CartItem
from orders.models import OrderItem
from django.db.models import Sum, Count
from django.utils import timezone
from django.db.models import Count

def is_artist(user):
    return user.groups.filter(name='Artists').exists() or user.is_superuser

@login_required
def artwork_list(request):
    artworks = Artwork.objects.filter(stock__gt=0)
    categories = Category.objects.all()
    
    # Filter by category if provided
    category_slug = request.GET.get('category')
    if category_slug:
        artworks = artworks.filter(category__slug=category_slug)
    
    context = {
        'artworks': artworks,
        'categories': categories,
    }
    return render(request, 'products/artwork_list.html', context)

def artwork_detail(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    
    if artwork.category:
        interests = request.session.get('interests', {})
        category_id = str(artwork.category.id)
        # Increment the "score" for this category
        interests[category_id] = interests.get(category_id, 0) + 1
        request.session['interests'] = interests
    
    context = {
        'artwork': artwork,
        'related_artworks': Artwork.objects.filter(category=artwork.category).exclude(pk=pk)[:4]
    }
    return render(request, 'products/artwork_detail.html', context)

@login_required
@user_passes_test(is_artist)
def artwork_create(request):
    if request.method == 'POST':
        form = ArtworkForm(request.POST, request.FILES)
        if form.is_valid():
            artwork = form.save(commit=False)
            artwork.artist = request.user
            artwork.save()
            form.save_m2m()  # Save many-to-many data
            messages.success(request, 'Artwork created successfully!')
            return redirect('artwork_detail', pk=artwork.pk)
    else:
        form = ArtworkForm()
    
    context = {
        'form': form,
        'title': 'Add New Artwork'
    }
    return render(request, 'products/artwork_form.html', context)

@login_required
@user_passes_test(is_artist)
def artwork_update(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    
    # Check if the user is the artist who created this artwork
    if artwork.artist != request.user and not request.user.is_superuser:
        messages.error(request, 'You can only edit your own artwork.')
        return redirect('artwork_list')
    
    if request.method == 'POST':
        form = ArtworkForm(request.POST, request.FILES, instance=artwork)
        if form.is_valid():
            form.save()
            messages.success(request, 'Artwork updated successfully!')
            return redirect('artwork_detail', pk=artwork.pk)
    else:
        form = ArtworkForm(instance=artwork)
    
    context = {
        'form': form,
        'title': 'Edit Artwork',
        'artwork': artwork
    }
    return render(request, 'products/artwork_form.html', context)

@login_required
@user_passes_test(is_artist)
def artwork_delete(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    
    # Check if the user is the artist who created this artwork
    if artwork.artist != request.user and not request.user.is_superuser:
        messages.error(request, 'You can only delete your own artwork.')
        return redirect('artwork_list')
    
    if request.method == 'POST':
        try:
            #! First, remove any cart items that reference this artwork
            try:
                from cart.models import CartItem
                CartItem.objects.filter(artwork=artwork).delete()
            except Exception as e:
                #! If cart items can't be deleted due to migration issues, continue anyway
                print(f"Warning: Could not delete cart items: {e}")
            
            #! Delete the artwork
            artwork.delete()
            messages.success(request, 'Artwork deleted successfully!')
            return redirect('artwork_list')
            
        except Exception as e:
            messages.error(request, f'Error deleting artwork: {str(e)}')
            return redirect('artwork_detail', pk=artwork.pk)
    
    context = {
        'artwork': artwork
    }
    return render(request, 'products/artwork_delete.html', context)

@login_required
@user_passes_test(is_artist)
def artist_dashboard(request):
    #! Get artist's artworks
    artworks = Artwork.objects.filter(artist=request.user).order_by('-created_at')

    artist_order_items = OrderItem.objects.filter(artwork__artist=request.user)
    
    #! Calculate statistics
    total_artworks = artworks.count()
    
    #! Calculate real sales data
    total_sales = artist_order_items.aggregate(total_sold=Sum('quantity'))['total_sold'] or 0
    total_revenue = sum(item.get_cost() for item in artist_order_items)

    #! Get paid orders only for revenue calculation
    paid_order_items = artist_order_items.filter(order__paid=True)
    actual_revenue = sum(item.get_cost() for item in paid_order_items)
    
    #! Best selling artwork
    best_selling = artist_order_items.values('artwork__title').annotate(
        total_sold=Sum('quantity')
    ).order_by('-total_sold').first()

    best_selling_artwork = None
    if best_selling:
        best_selling_artwork = Artwork.objects.filter(
            title=best_selling['artwork__title'],
            artist=request.user
        ).first()
    

    
    #! Calculate revenue from artworks (placeholder - will be replaced with actual order data)
    revenue_from_artworks = artworks.aggregate(total=Sum('price'))['total'] or 0
    
    #! Get recent artworks (last 5)
    recent_artworks = artworks[:5]
    
    #! orders this month
    this_month = timezone.now().month
    orders_this_month = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__created__month=this_month
    ).count()
    
    context = {
        'artworks': artworks,
        'recent_artworks': recent_artworks,
        'total_artworks': artworks.count(),
        'total_sales': total_sales,
        'total_revenue': actual_revenue,
        'revenue_from_artworks': total_revenue,
        'best_selling_artwork': best_selling_artwork,
        'orders_this_month': orders_this_month,
        'artist_order_items': artist_order_items,
    }
    return render(request, 'products/artist_dashboard.html', context)

@login_required
def user_view_of_artist(request, artist_id):
    artist = get_object_or_404(User, id=artist_id)

    artworks = Artwork.objects.filter(
        artist=artist
    ).order_by('-created_at')

    # check user profile for commission availability 
    artist_profile = getattr(artist, 'userprofile', None)

    form = CustomRequestForm()
    if request.method == 'POST' and 'submit_commission' in request.POST:
        form = CustomRequestForm(request.POST, request.FILES)
        commission = form.save(commit= False)
        #assign roles:
        commission.sender = request.user
        commission.receiver = artist
        commission.save()

        messages.success()

        messages.success(request, f"Your request has been sent to {artist.username}!")
        return redirect('user_view_of_artist', artist_id=artist_id)


    artist_order_items = OrderItem.objects.filter(
        artwork__artist=artist
    )

    best_selling = artist_order_items.values(
        'artwork'
    ).annotate(
        total_sold=Sum('quantity')
    ).order_by('-total_sold').first()

    best_selling_artwork = None
    if best_selling:
        best_selling_artwork = Artwork.objects.get(id=best_selling['artwork'])

    context = {
        'form': form,
        'artist_profile': artist_profile,
        'artist': artist,
        'artworks': artworks,
        'best_selling_artwork': best_selling_artwork,
    }
    return render(request, 'products/user_view_of_artist.html', context)