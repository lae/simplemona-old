import os
import logging

from flask.ext.script import Manager, Shell
from flask.ext.migrate import Migrate, MigrateCommand
from simplecoin import create_app, db

app = create_app()
manager = Manager(app)
migrate = Migrate(app, db)

root = os.path.abspath(os.path.dirname(__file__) + '/../')

from bitcoinrpc.authproxy import AuthServiceProxy
from simplecoin.tasks import (cleanup, payout, server_status, difficulty_avg,
                              update_online_workers, update_pplns_est,
                              cache_user_donation)
from simplecoin.models import (Transaction, Threshold, DonationPercent,
                               BonusPayout)
from simplecoin.utils import setfee_command
from flask import current_app, _request_ctx_stack

root = logging.getLogger()
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
root.addHandler(ch)
root.setLevel(logging.DEBUG)

hdlr = logging.FileHandler(app.config.get('manage_log_file', 'manage.log'))
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
root.addHandler(hdlr)
root.setLevel(logging.DEBUG)


@manager.command
def init_db():
    """ Resets entire database to empty state """
    with app.app_context():
        db.session.commit()
        db.drop_all()
        db.create_all()


@manager.command
def update_minimum_fee():
    """ Sets all custom fees in the database to be at least the minimum. Should
    be run after changing the minimum. """
    min_fee = current_app.config['minimum_perc']
    DonationPercent.query.filter(DonationPercent.perc < min_fee).update(
        {DonationPercent.perc: min_fee}, synchronize_session=False)
    db.session.commit()


@manager.option('fee')
@manager.option('user')
def set_fee(user, fee):
    """ Manually sets a fee percentage. """
    setfee_command(user, fee)


@manager.option('description', help="A plaintext description of the bonus payout")
@manager.option('amount', help="The amount in satoshi")
@manager.option('user', help="The users address")
def give_bonus(user, amount, description):
    """ Manually create a BonusPayout for a user """
    BonusPayout.create(user, amount, description)
    db.session.commit()


@manager.command
def list_fee_perc():
    """ Gives a summary of number of users at each fee amount """
    summ = {}
    warn = False
    for entry in DonationPercent.query.all():
        summ.setdefault(entry.perc, 0)
        summ[entry.perc] += 1
        if entry.perc < current_app.config['minimum_perc']:
            warn = True

    if warn:
        print("WARNING: A user is below the minimum configured value! "
              "Run update_minimum_fee command to resolve.")
    print "User fee summary"
    print "\n".join(["{0:+3d}% Fee: {1}".format(k, v) for k, v in sorted(summ.items())])


@manager.option('-s', '--simulate', dest='simulate', default=True)
def cleanup_cmd(simulate):
    """ Manually runs old share cleanup in simulate mode by default. """
    simulate = simulate != "0"
    cleanup(simulate=simulate)


@manager.option('-t', '--txid', dest='transaction_id')
def confirm_trans(transaction_id):
    """ Manually confirms a transaction. """
    trans = Transaction.query.filter_by(txid=transaction_id).first()
    trans.confirmed = True
    db.session.commit()


@manager.command
def reload_cached():
    """ Recomputes all the cached values that normally get refreshed by tasks.
    Good to run if celery has been down, site just setup, etc. """
    difficulty_avg()
    update_pplns_est()
    update_online_workers()
    cache_user_donation()
    server_status()


@manager.command
def test_email():
    """ Sends a testing email to the send address """
    thresh = Threshold(emails=[current_app.config['email']['send_address']])
    thresh.report_condition("Test condition")


@manager.option('-s', '--simulate', dest='simulate', default=True)
def payout_cmd(simulate):
    """ Runs the payout task manually. Simulate mode is default. """
    simulate = simulate != "0"
    payout(simulate=simulate)


def make_context():
    """ Setup a coinserver connection fot the shell context """
    app = _request_ctx_stack.top.app
    conn = AuthServiceProxy(
        "http://{0}:{1}@{2}:{3}/"
        .format(app.config['coinserv']['username'],
                app.config['coinserv']['password'],
                app.config['coinserv']['address'],
                app.config['coinserv']['port']))
    return dict(app=app, conn=conn)
manager.add_command("shell", Shell(make_context=make_context))
manager.add_command('db', MigrateCommand)


@manager.command
def runserver():
    current_app.run(debug=True, host='0.0.0.0')


if __name__ == "__main__":
    manager.run()
