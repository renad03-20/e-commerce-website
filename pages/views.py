from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from artwork.models import Artwork, Category

from django.contrib import messages
from .forms import CustomUserCreationForm

def home(request):
    interests = request.session.get('interests', {})
    categories = Category.objects.all()
    
    if interests:
        # Find the category ID with the highest score
        most_liked_category_id = max(interests, key=interests.get)
        
        # Pull art from that category first
        featured_artwork = Artwork.objects.filter(
            category_id=most_liked_category_id, 
            stock__gt=0
        ).order_by('?')[:4]
        
        # If they haven't seen enough of that category, fill the rest with random art
        if featured_artwork.count() < 4:
            additional = Artwork.objects.filter(stock__gt=0).exclude(
                category_id=most_liked_category_id
            ).order_by('?')[:4 - featured_artwork.count()]
            featured_artwork = list(featured_artwork) + list(additional)
    else:
        # Fallback for new users (Level 3: Trending/Random)
        featured_artwork = Artwork.objects.filter(stock__gt=0).order_by('?')[:4]

    context = {
        'featured_artwork': featured_artwork,
        'categories': categories[:4],
    }
    return render(request, "pages/home.html", context)

def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            return redirect('login')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'registration/signup.html', {"form": form})

def logoutpage(request):
    logout(request)
    return redirect('login')

def terms_of_service(request):
    """Terms of service page"""
    return render(request, 'pages/terms_of_service.html')

def privacy_policy(request):
    return render(request, 'pages/privacy_policy.html')

def contact(request):
    """Contact/Support page"""
    if request.method == 'POST':
        # In a real implementation, you would:
        # 1. Validate the form
        # 2. Send an email
        # 3. Store in database
        # For now, we'll just show a success message
        messages.success(request, 'Thank you for your message! We will get back to you within 24-48 hours.')
        return redirect('contact')
    return render(request, 'pages/contact.html')