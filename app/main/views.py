from flask import render_template, redirect, url_for, abort, flash, request, \
    current_app, make_response
from flask_login import login_required, current_user
from flask_sqlalchemy import get_debug_queries

from . import main
from .forms import EditProfileForm, EditProfileAdminForm, PostForm, \
    CommentForm, ContactForm
from .. import db
from ..decorators import admin_required, permission_required
from ..models import Permission, Role, User, Post, Comment, Topic, Like, Dislike
from datetime import datetime
from itertools import chain

from werkzeug.contrib.cache import SimpleCache

cache = SimpleCache()

@main.after_app_request
def after_request(response):
    for query in get_debug_queries():
        if query.duration >= current_app.config['FLASKY_SLOW_DB_QUERY_TIME']:
            current_app.logger.warning(
                'Slow query: %s\nParameters: %s\nDuration: %fs\nContext: %s\n'
                % (query.statement, query.parameters, query.duration,
                   query.context))
    return response


@main.route('/shutdown')
def server_shutdown():
    if not current_app.testing:
        abort(404)
    shutdown = request.environ.get('werkzeug.server.shutdown')
    if not shutdown:
        abort(500)
    shutdown()
    return 'Shutting down...'


@main.route('/', methods=['GET', 'POST'])
def index():
    form = PostForm()
    if current_user.can(Permission.WRITE_ARTICLES) and \
            form.validate_on_submit():
        post = Post(title=form.title.data,
                    sub_title=form.sub_title.data,
                    image=form.image.data,
                    body=form.body.data,
                    author=current_user._get_current_object())

        topics = form.topics.data
        clean_topics = "".join(topics.split())
        topics_list = clean_topics.split(',')
        capitalized = [topic.capitalize() for topic in topics_list]

        for topic in capitalized:
            exists = Topic.query.filter_by(topic=topic).all()
            if exists:
                post.topics.append(exists[0])

            else:
                new_topic = Topic(topic=topic)
                post.topics.append(new_topic)

        db.session.add(post)
        db.session.commit()

        return redirect(url_for('.index'))

    page = request.args.get('page', 1, type=int)
    show_followed = False
    if current_user.is_authenticated:
        show_followed = bool(request.cookies.get('show_followed', ''))
    if show_followed:
        query = current_user.followed_posts
    else:
        query = Post.query
    pagination = query.order_by(Post.timestamp.desc()).paginate(
        page, per_page=current_app.config['FLASKY_POSTS_PER_PAGE'],
        error_out=False)
    posts = pagination.items
    popular_posts = get_popular_posts()
    popular_topics = get_popular_topics()

    return render_template('index.html', popular_posts=popular_posts, popular_topics=popular_topics, form=form,
                           posts=posts, show_followed=show_followed, pagination=pagination)


def get_popular_posts():
    popular_posts = cache.get('popular-posts')
    if popular_posts is None:
        popular_posts = Post.get_trending_posts()
        cache.set('popular-posts', popular_posts, timeout=60 * 60)
    return popular_posts


def get_popular_topics():
    popular_topics = cache.get('popular-topics')
    if popular_topics is None:
        popular_topics = Topic.get_trending_topics()
        cache.set('popular-topics', popular_topics, timeout=60 * 60)
    return popular_topics


def get_recommended_for_you(id):
    original_post = Post.query.get_or_404(id)
    topics = original_post.topics.all()
    recommended = []
    for topic in topics:
        all_posts = topic.posts.all()
        for post in all_posts:
            if post not in recommended and post.id != id:
                recommended.append(post)
    return recommended


@main.route('/contact', methods=['GET', 'POST'])
def contact():
    form = ContactForm()

    if request.method == 'POST':
        if form.validate() == False:
            flash('All fields are required.')
            return render_template('contact.html', form=form)
        else:
            msg = Message(form.subject.data, sender='contact@example.com', recipients=['your_email@example.com'])
            msg.body = """
      From: %s <%s>
      %s
      """ % (form.name.data, form.email.data, form.message.data)
            mail.send(msg)

            return 'Form posted.'

    elif request.method == 'GET':
        return render_template('contact.html', form=form)

@main.route('/about')
def about():
    return render_template('about.html')

@main.route('/user/<username>')
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    pagination = user.posts.order_by(Post.timestamp.desc()).paginate(
        page, per_page=current_app.config['FLASKY_POSTS_PER_PAGE'],
        error_out=False)
    posts = pagination.items
    return render_template('user.html', user=user, posts=posts,
                           pagination=pagination)


@main.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.location = form.location.data
        current_user.about_me = form.about_me.data
        db.session.add(current_user)
        flash('Your profile has been updated.')
        return redirect(url_for('.user', username=current_user.username))
    form.name.data = current_user.name
    form.location.data = current_user.location
    form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', form=form)


@main.route('/edit-profile/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_profile_admin(id):
    user = User.query.get_or_404(id)
    form = EditProfileAdminForm(user=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.username = form.username.data
        user.confirmed = form.confirmed.data
        user.role = Role.query.get(form.role.data)
        user.name = form.name.data
        user.location = form.location.data
        user.about_me = form.about_me.data
        db.session.add(user)
        flash('The profile has been updated.')
        return redirect(url_for('.user', username=user.username))
    form.email.data = user.email
    form.username.data = user.username
    form.confirmed.data = user.confirmed
    form.role.data = user.role_id
    form.name.data = user.name
    form.location.data = user.location
    form.about_me.data = user.about_me
    return render_template('edit_profile.html', form=form, user=user)


@main.route('/post/<int:id>', methods=['GET', 'POST'])
def post(id):
    post = Post.query.get_or_404(id)
    topics = post.topics.all()
    if post.read_count is None:
        post.read_count = 0

    if current_user != post.author:
        post.read_count += 1
        for topic in topics:
            if post.read_count is None:
                topic.read_count = 0
                topic.read_count += 1

    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(body=form.body.data,
                          post=post,
                          author=current_user._get_current_object())
        db.session.add(comment)
        flash('Your comment has been published.')
        return redirect(url_for('.post', id=post.id, page=-1))
    page = request.args.get('page', 1, type=int)
    if page == -1:
        page = (post.comments.count() - 1) // \
               current_app.config['FLASKY_COMMENTS_PER_PAGE'] + 1
    pagination = post.comments.order_by(Comment.timestamp.asc()).paginate(
        page, per_page=current_app.config['FLASKY_COMMENTS_PER_PAGE'],
        error_out=False)
    comments = pagination.items
    popular_posts = get_popular_posts()
    popular_topics = get_popular_topics()
    recommended_for_you = get_recommended_for_you(id)
    return render_template('post.html', posts=[post],recommended_for_you=recommended_for_you,popular_posts=popular_posts,popular_topics=popular_topics, form=form,
                           comments=comments, pagination=pagination)


@main.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    post = Post.query.get_or_404(id)
    if current_user != post.author and \
            not current_user.can(Permission.ADMINISTER):
        abort(403)
    form = PostForm()
    if form.validate_on_submit():
        post.title = form.title.data
        post.sub_title = form.sub_title.data
        post.image = form.image.data
        post.body = form.body.data
        db.session.add(post)
        flash('The post has been updated.')
        return redirect(url_for('.post', id=post.id))
    form.title.data = post.title
    form.sub_title.data = post.sub_title
    form.image.data = post.image
    topic_data = ""
    for topic in post.topics:
        topic_data += topic.topic + ","

    form.topics.data = topic_data
    form.body.data = post.body
    return render_template('edit_post.html', form=form)


@main.route('/index/upvote/<int:id>', methods=['GET', 'POST'])
@login_required
def index_upvote(id):
    upvote(id)
    return redirect(request.referrer)


@main.route('/index/downvote/<int:id>', methods=['GET', 'POST'])
@login_required
def index_downvote(id):
    downvote(id)
    return redirect(request.referrer)


def upvote(id):
    post = Post.query.get_or_404(id)
    like = Like.query.filter_by(user_id=current_user.id, post_id=id).all()
    if post.up_votes is None:
        post.up_votes = 0
    if not like:
        post.up_votes += 1
        like = Like(user_id=current_user.id, post_id=id, timestamp=datetime.utcnow())
        db.session.add(like)
        db.session.commit()


def downvote(id):
    post = Post.query.get_or_404(id)
    dislike = Dislike.query.filter_by(user_id=current_user.id, post_id=id).all()

    if post.down_votes is None:
        post.down_votes = 0
    if not dislike:
        post.down_votes += 1
        dislike = Dislike(user_id=current_user.id, post_id=id, timestamp=datetime.utcnow())
        db.session.add(dislike)
        db.session.commit()




@main.route('/follow/<username>')
@login_required
@permission_required(Permission.FOLLOW)
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    if current_user.is_following(user):
        flash('You are already following this user.')
        return redirect(url_for('.user', username=username))
    current_user.follow(user)
    flash('You are now following %s.' % username)
    return redirect(url_for('.user', username=username))


@main.route('/unfollow/<username>')
@login_required
@permission_required(Permission.FOLLOW)
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    if not current_user.is_following(user):
        flash('You are not following this user.')
        return redirect(url_for('.user', username=username))
    current_user.unfollow(user)
    flash('You are not following %s anymore.' % username)
    return redirect(url_for('.user', username=username))


@main.route('/followers/<username>')
def followers(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followers.paginate(
        page, per_page=current_app.config['FLASKY_FOLLOWERS_PER_PAGE'],
        error_out=False)
    follows = [{'user': item.follower, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title="Followers of",
                           endpoint='.followers', pagination=pagination,
                           follows=follows)


@main.route('/followed-by/<username>')
def followed_by(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followed.paginate(
        page, per_page=current_app.config['FLASKY_FOLLOWERS_PER_PAGE'],
        error_out=False)
    follows = [{'user': item.followed, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title="Followed by",
                           endpoint='.followed_by', pagination=pagination,
                           follows=follows)


@main.route('/all')
@login_required
def show_all():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_followed', '', max_age=30 * 24 * 60 * 60)
    return resp


@main.route('/followed')
@login_required
def show_followed():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_followed', '1', max_age=30 * 24 * 60 * 60)
    return resp


@main.route('/moderate')
@login_required
@permission_required(Permission.MODERATE_COMMENTS)
def moderate():
    page = request.args.get('page', 1, type=int)
    pagination = Comment.query.order_by(Comment.timestamp.desc()).paginate(
        page, per_page=current_app.config['FLASKY_COMMENTS_PER_PAGE'],
        error_out=False)
    comments = pagination.items
    return render_template('moderate.html', comments=comments,
                           pagination=pagination, page=page)


@main.route('/moderate/enable/<int:id>')
@login_required
@permission_required(Permission.MODERATE_COMMENTS)
def moderate_enable(id):
    comment = Comment.query.get_or_404(id)
    comment.disabled = False
    db.session.add(comment)
    return redirect(url_for('.moderate',
                            page=request.args.get('page', 1, type=int)))


@main.route('/moderate/disable/<int:id>')
@login_required
@permission_required(Permission.MODERATE_COMMENTS)
def moderate_disable(id):
    comment = Comment.query.get_or_404(id)
    comment.disabled = True
    db.session.add(comment)
    return redirect(url_for('.moderate',
                            page=request.args.get('page', 1, type=int)))
