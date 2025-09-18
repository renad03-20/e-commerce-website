from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from .models import Artwork, Category, Tag
from .forms import ArtworkForm

def is_artist(user):
    return user.groups.filter(name='Artists').exists() or user.is_superuser

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
    context = {
        'artwork': artwork,
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
        artwork.delete()
        messages.success(request, 'Artwork deleted successfully!')
        return redirect('artwork_list')
    
    context = {
        'artwork': artwork
    }
    return render(request, 'products/artwork_delete.html', context)