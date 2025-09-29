def is_artist_processor(request):
    is_artist = False
    if request.user.is_authenticated:
        is_artist = request.user.groups.filter(name='Artists').exists() or request.user.is_superuser
        
    return {'is_artist': is_artist}
