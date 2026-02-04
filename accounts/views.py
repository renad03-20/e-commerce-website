from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import UserProfile, Address
from .forms import UserProfileForm, AddressForm, CommissionStatusForm
from orders.models import Order

@login_required
def profile(request):
    """User profile overview"""
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    # Handle the commission toggle form
    if request.method == 'POST' and 'update_commission' in request.POST:
        commission_form = CommissionStatusForm(request.POST, instance=profile)
        if commission_form.is_valid():
            commission_form.save()
            messages.success(request, "Commission status updated!")
            return redirect('accounts:profile') 
    else:
        commission_form = CommissionStatusForm(instance=profile)
    
    # Get user's recent orders
    recent_orders = Order.objects.filter(user=request.user).order_by('-created')[:5]
    
    # Get user's addresses
    addresses = Address.objects.filter(user=request.user)
    
    context = {
        'profile': profile,
        'recent_orders': recent_orders,
        'addresses': addresses,
    }
    return render(request, 'accounts/profile.html', context)

@login_required
def profile_edit(request):
    """Edit user profile"""
    try:
        profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=profile)
    
    return render(request, 'accounts/profile_edit.html', {'form': form})

@login_required
def address_list(request):
    """List user's addresses"""
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'accounts/address_list.html', {'addresses': addresses})

@login_required
def address_create(request):
    """Create new address"""
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            
            # If setting as default, unset other defaults of same type
            if address.is_default:
                Address.objects.filter(user=request.user, address_type=address.address_type, is_default=True).update(is_default=False)
            
            address.save()
            messages.success(request, 'Address added successfully!')
            return redirect('accounts:address_list')
    else:
        form = AddressForm()
    
    return render(request, 'accounts/address_form.html', {'form': form, 'title': 'Add New Address'})

@login_required
def address_edit(request, pk):
    """Edit existing address"""
    address = get_object_or_404(Address, pk=pk, user=request.user)
    
    if request.method == 'POST':
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            address = form.save(commit=False)
            
            # If setting as default, unset other defaults of same type
            if address.is_default:
                Address.objects.filter(user=request.user, address_type=address.address_type, is_default=True).update(is_default=False)
            
            address.save()
            messages.success(request, 'Address updated successfully!')
            return redirect('accounts:address_list')
    else:
        form = AddressForm(instance=address)
    
    return render(request, 'accounts/address_form.html', {'form': form, 'title': 'Edit Address'})

@login_required
def address_delete(request, pk):
    """Delete address"""
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == 'POST':
        address.delete()
        messages.success(request, 'Address deleted successfully!')
        return redirect('accounts:address_list')
    
    return render(request, 'accounts/address_confirm_delete.html', {'address': address})

@login_required
def order_history(request):
    """User's complete order history"""
    orders = Order.objects.filter(user=request.user).order_by('-created')
    return render(request, 'accounts/order_history.html', {'orders': orders})