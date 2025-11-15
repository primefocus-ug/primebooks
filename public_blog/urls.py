from django.urls import path
from .views import (
    BlogHomeView, BlogDetailView, BlogCategoryView,
    BlogSearchView, AddCommentView, NewsletterSubscribeView,
    NewsletterUnsubscribeView
)

app_name = 'public_blog'

urlpatterns = [
    path('', BlogHomeView.as_view(), name='home'),
    path('search/', BlogSearchView.as_view(), name='search'),
    path('category/<slug:slug>/', BlogCategoryView.as_view(), name='category'),
    path('post/<slug:slug>/', BlogDetailView.as_view(), name='detail'),
    path('post/<slug:slug>/comment/', AddCommentView.as_view(), name='add_comment'),
    path('newsletter/subscribe/', NewsletterSubscribeView.as_view(), name='newsletter_subscribe'),
    path('newsletter/unsubscribe/<str:token>/', NewsletterUnsubscribeView.as_view(), name='newsletter_unsubscribe'),
]