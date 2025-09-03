from django.shortcuts import render
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.decorators import login_required
# Create your views here.

@login_required
def home(request):
    return render(request, "pages/home.html", {})

def login(request):
    return render(request, 'pages/templates/registration/login.html')

def authview(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST or None)
        if form.is_valid():
            form.save()
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {"form": form})