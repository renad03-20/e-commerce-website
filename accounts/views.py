from django.db import transaction
from artwork.permissions import is_artist_account
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import UserProfile, Address
from .forms import UserProfileForm, AddressForm, CommissionStatusForm
from orders.models import Order

@login_required
@transaction.atomic
def profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile = UserProfile.objects.select_for_update().get(pk=profile.pk)
    artist_role = is_artist_account(request.user)
    commission_form = CommissionStatusForm(instance=profile) if artist_role else None
    if request.method == 'POST' and 'update_commission' in request.POST:
        if not artist_role:
            messages.error(request, 'Only artist accounts can accept commission requests.')
            return redirect('accounts:profile')
        commission_form = CommissionStatusForm(request.POST, instance=profile)
        if commission_form.is_valid():
            commission_form.save()
            messages.success(request, 'Commission availability updated!')
            return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {
        'profile': profile, 'commission_form': commission_form, 'is_artist': artist_role,
        'recent_orders': Order.objects.filter(user=request.user).order_by('-created')[:5],
        'addresses': Address.objects.filter(user=request.user),
    })

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