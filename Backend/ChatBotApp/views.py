from rest_framework.response import Response
from django.http import Http404
from rest_framework.decorators import api_view
from rest_framework import status, viewsets
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .models import Message, Conversation
from .serializers import MessageSerializer, ConversationSerializer


@api_view(['GET'])
def server_status(request):
    return Response({'status': 'ok'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@extend_schema(
    parameters=[
        OpenApiParameter(name='token', description='Conversation token', required=True, type=str),
    ],
    responses={
        200: ConversationSerializer,
        400: 'Bad Request',
    },
)


def get_conversation_messages(request, token):
    try:
        messages = Message.objects.filter(conversation__token=token).order_by('timestamp')
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)



class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    lookup_field = 'token'
    def get_object(self):
        token = self.kwargs.get('token')
        try:
            return Conversation.objects.get(token=token)
        except Conversation.DoesNotExist:
            raise Http404("Conversation not found")
        
