from django.shortcuts import render
from django.http import HttpRequest, HttpResponse

# Create your views here.
# here is the place where a requist is given a response 
# a requist handler


#! in the function we can do a lot of things
#? pull data from database
#? transform data
#? send emails

def say_hello(request):
    x = 1
    y = 2
    return render(request, 'hello.html', {'name': 'mosh'})