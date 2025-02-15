# best_setup_voting.py

import os
import logging
import traceback
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy.exc import IntegrityError

from flask import Blueprint, request, render_template, flash, redirect, url_for, session, current_app
from models import db, User, Trade, Setup, Criterion, Config, BestSetupCandidate, BestSetupVote, BestSetupPoll
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account

logger = logging.getLogger(__name__)

best_setup_voting_bp = Blueprint('best_setup_voting', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or 'telegram_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        from app import ADMIN_TELEGRAM_IDS
        if session['telegram_id'] not in ADMIN_TELEGRAM_IDS:
            flash('Access denied.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.assistant_premium:
            flash('Access denied. Purchase a premium subscription.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def ensure_wallet(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        if not user.wallet_address:
            flash('Please enter your wallet address to participate in voting.', 'info')
            return redirect(url_for('best_setup_voting.set_wallet'))
        return f(*args, **kwargs)
    return decorated_function

def get_active_poll():
    now = datetime.utcnow()
    poll = BestSetupPoll.query.filter(BestSetupPoll.status == 'active', BestSetupPoll.end_date > now).first()
    return poll

### ЛОГИКА ОТПРАВКИ ТОКЕНОВ ###
BASE_RPC_URL = os.environ.get('BASE_RPC_URL', '')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY', '')
TOKEN_CONTRACT_ADDRESS = os.environ.get('TOKEN_CONTRACT_ADDRESS', '')
TOKEN_DECIMALS = int(os.environ.get('TOKEN_DECIMALS', '18'))

web3 = None
token_contract = None
account = None

if BASE_RPC_URL and PRIVATE_KEY and TOKEN_CONTRACT_ADDRESS:
    web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
    if web3.is_connected():
        logger.info("Подключено к RPC сети Base.")
        web3.middleware_onion.inject(geth_poa_middleware, layer=0)
        try:
            account = Account.from_key(PRIVATE_KEY)
            logger.info(f"Аккаунт инициализирован: {account.address}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации аккаунта: {e}")
            account = None

        ERC20_ABI = [
            {
                "constant": False,
                "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
                "name": "transfer",
                "outputs": [{"name": "success", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }
        ]

        try:
            token_contract = web3.eth.contract(
                address=Web3.to_checksum_address(TOKEN_CONTRACT_ADDRESS),
                abi=ERC20_ABI
            )
            logger.info(f"Токен-контракт инициализирован: {TOKEN_CONTRACT_ADDRESS}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации токен-контракта: {e}")
            token_contract = None
    else:
        logger.error("Не удалось подключиться к сети Base.")
else:
    logger.error("Не все необходимые переменные окружения установлены (BASE_RPC_URL, PRIVATE_KEY, TOKEN_CONTRACT_ADDRESS).")

def send_token_reward(user_wallet, amount):
    if not account or not token_contract:
        logger.error("Нет настроек для отправки токенов.")
        return False

    if not user_wallet or not user_wallet.startswith('0x') or len(user_wallet) != 42:
        logger.warning(f"Некорректный адрес кошелька: {user_wallet}")
        return False

    try:
        # Используем параметр 'pending' для корректного получения nonce
        nonce = web3.eth.get_transaction_count(account.address, 'pending')
        token_amount = int(amount * (10**TOKEN_DECIMALS))

        tx = token_contract.functions.transfer(
            Web3.to_checksum_address(user_wallet),
            token_amount
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': Web3.to_wei('1', 'gwei')
        })

        signed_tx = web3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt and receipt.status == 1:
            logger.info(f"Отправлено {amount} токенов на {user_wallet}. TX: {receipt.transactionHash.hex()}")
            return True
        else:
            logger.error(f"Транзакция неудачна или нет статуса: {receipt}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при отправке токенов: {e}")
        logger.error(traceback.format_exc())
        return False

### АНТИ-СПАМ МЕХАНИЗМ ###
# def is_spammer(user_id):
#     # Если хотя бы 2 дня из последних 7 дней было >=10 сделок в день, то спамщик.
#     now = datetime.utcnow()
#     spam_days = 0
#     for i in range(7):
#         day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
#         day_end = day_start + timedelta(days=1)
#         daily_count = Trade.query.filter(
#             Trade.user_id == user_id,
#             Trade.trade_open_time >= day_start,
#             Trade.trade_open_time < day_end
#         ).count()
#         if daily_count >= 10:
#             spam_days += 1
#     if spam_days >= 2:
#         return True
#     return False

def generate_s3_url(filename: str) -> str:
    bucket_name = current_app.config['AWS_S3_BUCKET']
    region = current_app.config['AWS_S3_REGION']
    if region == 'us-east-1':
        url = f"https://{bucket_name}.s3.amazonaws.com/{filename}"
    else:
        url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{filename}"
    return url

### ЛОГИКА ГОЛОСОВАНИЯ ###

@best_setup_voting_bp.route('/start_best_setup_contest', methods=['POST'])
@admin_required
def start_best_setup_contest():
    active_poll = get_active_poll()
    if active_poll:
        flash("There is already an active poll.", "info")
        return redirect(url_for('admin_users'))

    last_poll_conf = Config.query.filter_by(key='last_best_setup_poll').first()
    if last_poll_conf:
        try:
            last_poll_date = datetime.strptime(last_poll_conf.value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # Попытка парсинга старого формата
            try:
                last_poll_date = datetime.strptime(last_poll_conf.value, '%Y-%m-%d')
                last_poll_conf.value = last_poll_date.strftime('%Y-%m-%d %H:%M:%S')
                db.session.commit()
                logger.info("last_best_setup_poll обновлён до нового формата.")
            except ValueError:
                flash("Invalid date format for the last poll.", "danger")
                logger.error("Неверный формат даты в last_best_setup_poll.")
                return redirect(url_for('admin_users'))

        time_diff = datetime.utcnow() - last_poll_date
        if time_diff.total_seconds() / 60 < 15:
            flash("Polls can only be started every 15 minutes; too early.", "warning")
            return redirect(url_for('admin_users'))

    # Установка длительности голосования на 15 минут
    start_date = datetime.utcnow()
    end_date = start_date + timedelta(days=30)

    # Очистка предыдущих данных голосования
    try:
        BestSetupVote.query.delete()
        BestSetupCandidate.query.delete()
        BestSetupPoll.query.delete()
        db.session.commit()
        logger.info("Предыдущие данные голосования успешно удалены.")
    except Exception as e:
        logger.error(f"Ошибка при удалении предыдущих данных голосования: {e}")
        db.session.rollback()
        flash("Error initializing new poll.", "danger")
        return redirect(url_for('admin_users'))

    # Создание нового голосования
    try:
        poll = BestSetupPoll(start_date=start_date, end_date=end_date, status='active')
        db.session.add(poll)
        db.session.commit()
        logger.info("Новое голосование успешно создано.")

        if not last_poll_conf:
            last_poll_conf = Config(key='last_best_setup_poll', value=start_date.strftime('%Y-%m-%d %H:%M:%S'))
            db.session.add(last_poll_conf)
        else:
            last_poll_conf.value = start_date.strftime('%Y-%m-%d %H:%M:%S')
        db.session.commit()
        logger.info("Конфигурация последнего голосования обновлена.")

        premium_users = User.query.filter_by(assistant_premium=True).all()
        candidates = []

        for user in premium_users:
            # if is_spammer(user.id):
            #     logger.info(f"Пользователь {user.id} помечен как спамер и пропущен.")
            #     continue
            setups = user.setups
            for setup in setups:
                trades = Trade.query.filter_by(user_id=user.id, setup_id=setup.id).all()
                total_trades = len(trades)
                if total_trades < 10:
                    logger.info(f"Сетап {setup.id} пользователя {user.id} имеет недостаточное количество сделок.")
                    continue
                wins = sum(1 for t in trades if t.profit_loss and t.profit_loss > 0)
                win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0
                if win_rate < 65 or win_rate > 90:
                    logger.info(f"Сетап {setup.id} пользователя {user.id} имеет низкий/высокий Win Rate {win_rate}%.")
                    continue
                candidates.append({
                    'user_id': user.id,
                    'setup_id': setup.id,
                    'total_trades': total_trades,
                    'win_rate': win_rate
                })

        candidates.sort(key=lambda x: (x['win_rate'], x['total_trades']), reverse=True)
        top_candidates = candidates[:15]
        logger.info(f"Найдено {len(top_candidates)} топ-кандидатов для голосования.")

        for c in top_candidates:
            # Получаем объект сетапа для извлечения изображения
            setup_obj = Setup.query.get(c['setup_id'])
            voting_screenshot = None
            if setup_obj and setup_obj.screenshot:
                voting_screenshot = generate_s3_url(setup_obj.screenshot)
            candidate = BestSetupCandidate(
                user_id=c['user_id'],
                setup_id=c['setup_id'],
                poll_id=poll.id,
                total_trades=c['total_trades'],
                win_rate=c['win_rate'],
                voting_screenshot=voting_screenshot  # Фиксированное изображение для голосования
            )
            db.session.add(candidate)
        db.session.commit()
        logger.info("Кандидаты успешно добавлены в новое голосование.")

        flash("Poll started for 15 minutes.", "success")
        return redirect(url_for('admin_users'))
    except Exception as e:
        logger.error(f"Ошибка при создании кандидатов или голосования: {e}")
        db.session.rollback()
        flash("Error initializing new poll.", "danger")
        return redirect(url_for('admin_users'))

@best_setup_voting_bp.route('/best_setup_candidates', methods=['GET'])
@premium_required
def best_setup_candidates():
    poll = get_active_poll()
    if not poll:
        flash("There is no active poll right now.", "info")
        return redirect(url_for('index'))

    candidates = BestSetupCandidate.query.filter_by(poll_id=poll.id).order_by(
        BestSetupCandidate.win_rate.desc(),
        BestSetupCandidate.total_trades.desc()
    ).all()
    candidates_list = []

    for c in candidates:
        setup = Setup.query.get(c.setup_id)
        if setup:
            # Если для кандидата уже зафиксировано изображение, используем его
            if c.voting_screenshot:
                screenshot_url = c.voting_screenshot
            else:
                screenshot_url = generate_s3_url(setup.screenshot) if setup.screenshot else None
            criteria_list = [criterion.name for criterion in setup.criteria]
        else:
            logger.warning(f"Setup with id {c.setup_id} not found for candidate {c.id}")
            screenshot_url = None
            criteria_list = []

        candidate_dict = {
            'id': c.id,
            'setup_name': setup.setup_name if setup else "Unknown",
            'description': setup.description if setup else "No description",
            'screenshot_url': screenshot_url,
            'criteria': criteria_list,
            'total_trades': c.total_trades,
            'win_rate': c.win_rate
        }
        candidates_list.append(candidate_dict)

    logger.debug(f"Переданные кандидаты: {candidates_list}")

    return render_template('best_setup_candidates.html', candidates=candidates_list)

@best_setup_voting_bp.route('/vote_best_setup', methods=['POST'])
@premium_required
@ensure_wallet
def vote_best_setup():
    poll = get_active_poll()
    if not poll:
        flash("There is no active poll.", "info")
        return redirect(url_for('index'))

    logger.debug(f"Полученные данные формы: {request.form}")

    candidate_id = request.form.get('candidate_id')
    if not candidate_id:
        flash('No candidate selected for voting.', 'danger')
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    try:
        candidate_id = int(candidate_id)
    except ValueError:
        flash('Invalid candidate ID.', 'danger')
        logger.error(f"Некорректный идентификатор кандидата: {candidate_id}")
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    candidate = BestSetupCandidate.query.filter_by(id=candidate_id, poll_id=poll.id).first()
    if not candidate:
        flash('Invalid candidate.', 'danger')
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    user_id = session['user_id']
    
    # Проверка, голосовал ли пользователь уже в этом голосовании
    existing_vote = BestSetupVote.query.join(BestSetupCandidate).filter(
        BestSetupVote.voter_user_id == user_id,
        BestSetupCandidate.poll_id == poll.id
    ).first()
    
    if existing_vote:
        flash('You have already voted in this poll.', 'info')
        return redirect(url_for('best_setup_voting.best_setup_candidates'))

    vote = BestSetupVote(
        voter_user_id=user_id,
        candidate_id=candidate_id
    )
    db.session.add(vote)
    db.session.commit()

    flash('Your vote has been recorded!', 'success')
    return redirect(url_for('best_setup_voting.best_setup_candidates'))

@best_setup_voting_bp.route('/set_wallet', methods=['GET', 'POST'])
def set_wallet():
    user_id = session['user_id']
    user = User.query.get(user_id)
    if request.method == 'POST':
        wallet = request.form.get('wallet_address')
        if wallet and wallet.startswith('0x') and len(wallet) == 42:
            user.wallet_address = wallet
            try:
                db.session.commit()  # Пробуем сохранить
                flash('Wallet address saved successfully.', 'success')
                return redirect(url_for('best_setup_voting.best_setup_candidates'))
            except IntegrityError:
                # Откатываем транзакцию, выводим предупреждение
                db.session.rollback()
                flash('This wallet is already used by another user.', 'danger')
                return redirect(url_for('best_setup_voting.set_wallet'))
        else:
            flash('Invalid wallet address.', 'danger')

    return render_template('set_wallet.html', user=user)

def auto_finalize_best_setup_voting():
    from routes import bot  # Импортируем бота, чтобы можно было отправить сообщение
    
    poll = BestSetupPoll.query.filter_by(status='active').first()
    if not poll:
        return
    now = datetime.utcnow()
    if now >= poll.end_date:
        # Собираем результаты
        candidates = BestSetupCandidate.query.filter_by(poll_id=poll.id).all()
        results = []
        for c in candidates:
            vote_count = BestSetupVote.query.filter_by(candidate_id=c.id).count()
            results.append((c, vote_count))

        # Сортируем по числу голосов (по убыванию)
        results.sort(key=lambda x: x[1], reverse=True)

        # Берём топ-3
        winners = results[:3]
        
        # Узнаём, какой пул нужно распределить
        from models import Config, User  # на всякий случай импорт
        pool_config = Config.query.filter_by(key='best_setup_pool_size').first()
        pool_size = float(pool_config.value) if pool_config else 0.0
        
        # Распределение (70% победителям, 30% голосовавшим)
        winners_part = pool_size * 0.70
        voters_part  = pool_size * 0.30
        
        # Если меньше трёх, раздаём только тем, кто есть
        # first_w, second_w, third_w = winners[0], winners[1], winners[2], 
        # Но надо быть аккуратными: winners может быть меньше 3
        first_place_amount  = winners_part * 0.35
        second_place_amount = winners_part * 0.25
        third_place_amount  = winners_part * 0.20
        
        def safe_get_winner(winners, index):
            return winners[index] if index < len(winners) else None
        
        first_candidate = safe_get_winner(winners, 0)
        second_candidate= safe_get_winner(winners, 1)
        third_candidate = safe_get_winner(winners, 2)
        
        # Функция отправки награды + уведомления
        def reward_user(user_obj, amount, reason=""):
            if not user_obj or not user_obj.wallet_address:
                logger.warning(f"Не удалось наградить user_id={user_obj.id if user_obj else '???'}: нет wallet_address.")
                return
            success = send_token_reward(user_obj.wallet_address, amount)
            if success:
                logger.info(f"{reason} Пользователь {user_obj.id} получил {amount} UJO.")
                # Отправляем через телеграм
                try:
                    if user_obj.telegram_id:
                        bot.send_message(
                            chat_id=user_obj.telegram_id,
                            text=f"Congratulations! You have been awarded {amount:.4f} UJO {reason}"
                        )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления TG: {e}")
            else:
                logger.error(f"Не удалось отправить {amount} UJO пользователю {user_obj.id}.")

        # Награждаем призёров
        if first_candidate:
            c, votes = first_candidate
            winner_user = User.query.get(c.user_id)
            reward_user(winner_user, first_place_amount, reason="for 1st place in the poll!")
        
        if second_candidate:
            c, votes = second_candidate
            winner_user = User.query.get(c.user_id)
            reward_user(winner_user, second_place_amount, reason="for 2nd place in the poll!")
        
        if third_candidate:
            c, votes = third_candidate
            winner_user = User.query.get(c.user_id)
            reward_user(winner_user, third_place_amount, reason="for 3rd place in the poll!")
        
        # Награждаем голосовавших за победителей
        winner_candidate_ids = []
        for w in winners:
            winner_candidate_ids.append(w[0].id)
        
        winning_votes = BestSetupVote.query.filter(
            BestSetupVote.candidate_id.in_(winner_candidate_ids)
        ).all()

        # Собираем уникальный список user_id, которые проголосовали за ЛЮБОГО из призёров
        rewarded_voters_ids = set()
        for vote in winning_votes:
            rewarded_voters_ids.add(vote.voter_user_id)
        
        # Сколько таких?
        total_voters = len(rewarded_voters_ids)
        if total_voters > 0:
            each_voter_reward = voters_part / total_voters
            for voter_id in rewarded_voters_ids:
                voter = User.query.get(voter_id)
                reward_user(voter, each_voter_reward, reason="for voting for a winner in the poll!")
        
        # Завершаем голосование, ставим статус completed
        poll.status = 'completed'
        db.session.commit()
        logger.info(f"Голосование ID {poll.id} завершено автоматически, пул={pool_size} UJO распределён.")

@best_setup_voting_bp.route('/force_finalize_best_setup_voting', methods=['POST'])
@admin_required
def force_finalize_best_setup_voting():
    """Принудительно завершаем текущее голосование для тестирования."""
    poll = BestSetupPoll.query.filter_by(status='active').first()
    if not poll:
        flash("No active poll to finalize.", "warning")
        return redirect(url_for('admin_users'))

    poll.end_date = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    auto_finalize_best_setup_voting()

    flash("Active poll has been forcefully finalized.", "success")
    return redirect(url_for('admin_users'))

@best_setup_voting_bp.route('/delete_wallet', methods=['POST'])
def delete_wallet():
    """Удаляет wallet_address пользователя.
       Если пользователь участвует в актуальном голосовании или претендует на награды,
       можно добавить проверки и выводить предупреждение либо блокировать удаление."""
    user_id = session.get('user_id')
    if not user_id:
        flash("Please log in first.", "warning")
        return redirect(url_for('best_setup_voting.set_wallet'))

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('best_setup_voting.set_wallet'))

    # -- Пример дополнительной проверки:
    # active_poll = BestSetupPoll.query.filter_by(status='active').first()
    # if active_poll:
    #     flash("You cannot remove your wallet while an active poll is running!", "danger")
    #     return redirect(url_for('best_setup_voting.set_wallet'))

    # Сбрасываем кошелек
    user.wallet_address = None
    db.session.commit()

    flash("Wallet address has been removed. You will not receive any pending rewards unless you re-add a wallet.", "warning")
    return redirect(url_for('best_setup_voting.set_wallet'))

def init_best_setup_voting_routes(app, db_instance):
    app.register_blueprint(best_setup_voting_bp)
