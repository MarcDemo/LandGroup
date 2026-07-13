from messaging.models import Message, MessageRecipient

def unread_messages_count(request):
    if request.user.is_authenticated:
        count = MessageRecipient.objects.filter(recipient=request.user, is_read=False).count()
        return {'unread_count': count}
    return {}
