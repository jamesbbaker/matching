from clerk.processors.Stripe import Stripe
from config import database
import pendulum

class Billable(object):
    prorate_plan = True

    def __init__(self):
        print('billable instantiated')
    
    def charge(self, token, amount):
        return Stripe().charge(token, amount, "Charge for {0}".format(self.email))

    def customer(self, token, description=False):
        if not description:
            description = "Customer for {0}".format(self.email)
        
        transaction = Stripe().customer(token, description)
        self.stripe_id = transaction['id']
        self.save()
        return transaction

    def subscribe(self, subscription, plan, token):
        if not self.getCustomer():
            self.customer(token)

        subscribe = Stripe().subscribe(subscription, plan, self.stripe_id)

        # Trial Ends
        if subscribe['trial_end']:
            trial_ends_at = pendulum.from_timestamp(
                subscribe['trial_end']).to_datetime_string()
        else:
            trial_ends_at = None

        # Subscription Ends
        if subscribe['current_period_end']:
            ends_at = pendulum.from_timestamp(
                subscribe['current_period_end']).to_datetime_string()
        else:
            ends_at = None

        database.db.table('subscriptions').insert({
            'user_id': self.id,
            'name': subscription,
            'stripe_id': subscribe['id'],  # needs to be differnet
            'stripe_plan': plan,
            'trial_ends_at': trial_ends_at,
            'ends_at': ends_at,
            'quantity': 1,
        })

        return subscribe

    def getSubscription(self):
        subscription = database.db.table('subscriptions').where('user_id', self.id).first()
        if subscription:
            return Stripe().getSubscription(subscription['stripe_id'])

        return None

    def cancel(self, now=False):
        subscription = database.db.table(
            'subscriptions').where('user_id', self.id).first()
        if not subscription:
            return None

        cancel_subscription = Stripe().cancel(subscription['stripe_id'])
        subscription.delete()
        return cancel_subscription

    def getCustomer(self):
        if self.stripe_id:
            return Stripe().getCustomer(self.stripe_id)

        return None

    def deleteCustomer(self):
        customer = self.getCustomer()
        return customer.delete()

    def swap(self, new_plan):
        subscription = database.db.table(
            'subscriptions').where('user_id', self.id)

        if subscription.first():
            stripe_swap = Stripe().swapPlan(new_plan, subscription.first()['stripe_id'], self.prorate_plan)
            subscription.update(stripe_plan=new_plan)
            return stripe_swap
        
        return None

    def noProrate(self):
        self.prorate_plan = False
        return self

    def subscribedToPlan(self, plans):
        subscription = database.db.table(
            'subscriptions').where('user_id', self.id).first()
        # if plan is a list
        if isinstance(plans, list):
            for plan in plans:
                if subscription.stripe_plan == plan:
                    return True
            
            return False
        else:
            if subscription.stripe_plan == plans:
                return True

            return False
    
    def subscribed(self, plans=False):
        subscription = database.db.table(
            'subscriptions').where('user_id', self.id).first()

        if subscription:
            if not plans:
                if subscription:
                    return True
                else:
                    return False
            elif isinstance(plans, list):
                for plan in plans:
                    if subscription.name == plan:
                        return True
            else:
                if subscription.name == plans:
                    return True
        return False
