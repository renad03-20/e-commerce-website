from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from artwork.models import Artwork, Category

from django.contrib import messages
from .forms import CustomUserCreationForm

def home(request):
    #! getting tandom artwork to feature in the home page
    featured_artwork = Artwork.objects.filter(stock__gt=0).order_by('?')[:4]
    Categories = Category.objects.all()[:4] #! getting four categories for dispaly

    context = {
        'featured_artwork': featured_artwork,
        'Categories': Categories,
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