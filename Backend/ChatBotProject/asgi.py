import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from ChatBotApp.routing import websoket_urlpatterns

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ChatBotProject.settings')

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(), 
        "websocket": URLRouter(websoket_urlpatterns)
    })
